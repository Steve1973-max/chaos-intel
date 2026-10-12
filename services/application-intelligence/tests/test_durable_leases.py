import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base, LeaseRecordModel
from src.execution.persistence.repositories import SqlAlchemyLeaseRepository
from src.execution.reliability.errors import LeaseAcquisitionError, LeaseOwnershipError

@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def test_1_acquire_success_and_fencing_progression(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    
    # Initial acquire
    lease1 = repo.acquire("res-1", "owner-1", 60)
    assert lease1.resource_id == "res-1"
    assert lease1.owner_id == "owner-1"
    assert lease1.status == "active"
    assert lease1.version == 1
    assert lease1.fencing_token == 1
    
    # Release it
    repo.release("res-1", "owner-1", lease1.fencing_token)
    
    # Re-acquire (simulating subsequent acquisition)
    lease2 = repo.acquire("res-1", "owner-2", 60)
    assert lease2.owner_id == "owner-2"
    assert lease2.status == "active"
    assert lease2.version == 2
    assert lease2.fencing_token == 2

def test_2_contention_rejected(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    repo.acquire("res-2", "owner-1", 60)
    
    with pytest.raises(LeaseAcquisitionError, match="actively held"):
        repo.acquire("res-2", "owner-2", 60)

def test_3_wrong_owner_renewal_release(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease = repo.acquire("res-3", "owner-1", 60)
    
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid lease renewal"):
        repo.renew("res-3", "owner-2", lease.fencing_token, 60)
        
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid lease release"):
        repo.release("res-3", "owner-2", lease.fencing_token)

def test_4_stale_fencing_token_renewal_release(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease = repo.acquire("res-4", "owner-1", 60)
    
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid lease renewal"):
        repo.renew("res-4", "owner-1", lease.fencing_token - 1, 60)
        
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid lease release"):
        repo.release("res-4", "owner-1", lease.fencing_token - 1)

def test_5_expiry_allows_new_owner(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    import datetime
    
    # Manually insert an expired lease
    expired_lease = LeaseRecordModel(
        resource_id="res-5",
        owner_id="owner-1",
        status="active",
        version=1,
        fencing_token=1,
        acquired_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5),
        expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    )
    sqlite_session.add(expired_lease)
    sqlite_session.commit()
    
    # New owner should successfully acquire
    lease = repo.acquire("res-5", "owner-2", 60)
    assert lease.owner_id == "owner-2"
    assert lease.version == 2
    assert lease.fencing_token == 2

def test_6_validate_fencing_token(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease = repo.acquire("res-6", "owner-1", 60)
    
    # Valid
    assert repo.validate_fencing_token("res-6", lease.fencing_token) is True
    
    # Invalid token
    assert repo.validate_fencing_token("res-6", 999) is False
    
    # Invalidated by release
    repo.release("res-6", "owner-1", lease.fencing_token)
    assert repo.validate_fencing_token("res-6", lease.fencing_token) is False

def test_7_stale_owner_rejected_from_lease_writes(sqlite_session):
    repo = SqlAlchemyLeaseRepository(sqlite_session)
    import datetime
    
    # Owner 1 acquires token 1
    lease1 = repo.acquire("res-7", "owner-1", 60)
    
    # Its lease expires (simulate by setting expires_at in the past)
    model = sqlite_session.query(LeaseRecordModel).filter_by(resource_id="res-7").first()
    model.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    sqlite_session.commit()
    
    # Owner 2 acquires token 2
    lease2 = repo.acquire("res-7", "owner-2", 60)
    assert lease2.fencing_token == lease1.fencing_token + 1
    
    # Owner 1 attempts a protected database write (e.g. renew) using token 1
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid lease renewal"):
        repo.renew("res-7", "owner-1", lease1.fencing_token, 60)
        
    # The newer owner's state must remain intact
    assert repo.validate_fencing_token("res-7", lease2.fencing_token) is True
