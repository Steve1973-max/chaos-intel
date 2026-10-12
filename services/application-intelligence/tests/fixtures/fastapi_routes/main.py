from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/api/v1")

@app.get("/users")
def get_users():
    pass

@app.post("/users")
def create_user():
    pass

@router.get("/items/{id}")
def get_item(id: int):
    pass
