from dataclasses import dataclass, field
from typing import List

@dataclass
class TechnologyDefinition:
    name: str
    category: str
    package_names: List[str] = field(default_factory=list)
    file_extensions: List[str] = field(default_factory=list)
    manifest_files: List[str] = field(default_factory=list)
    config_signatures: List[str] = field(default_factory=list)

REGISTRY = [
    # Languages
    TechnologyDefinition("Python", "language", file_extensions=[".py"]),
    TechnologyDefinition("JavaScript", "language", file_extensions=[".js", ".jsx"]),
    TechnologyDefinition("TypeScript", "language", file_extensions=[".ts", ".tsx"], package_names=["typescript"]),
    TechnologyDefinition("Java", "language", file_extensions=[".java"]),
    TechnologyDefinition("C#", "language", file_extensions=[".cs"]),
    TechnologyDefinition("Go", "language", file_extensions=[".go"]),
    TechnologyDefinition("Rust", "language", file_extensions=[".rs"]),
    TechnologyDefinition("PHP", "language", file_extensions=[".php"]),
    TechnologyDefinition("Ruby", "language", file_extensions=[".rb"]),
    TechnologyDefinition("C", "language", file_extensions=[".c", ".h"]),
    TechnologyDefinition("C++", "language", file_extensions=[".cpp", ".cc", ".cxx", ".hpp"]),

    # Frontend
    TechnologyDefinition("React", "frontend", package_names=["react", "react-dom"]),
    TechnologyDefinition("Next.js", "frontend", package_names=["next"]),
    TechnologyDefinition("Vue", "frontend", package_names=["vue"]),
    TechnologyDefinition("Angular", "frontend", package_names=["@angular/core"]),
    TechnologyDefinition("Svelte", "frontend", package_names=["svelte"]),

    # Backend
    TechnologyDefinition("FastAPI", "backend", package_names=["fastapi"]),
    TechnologyDefinition("Flask", "backend", package_names=["flask"]),
    TechnologyDefinition("Django", "backend", package_names=["django"]),
    TechnologyDefinition("Express", "backend", package_names=["express"]),
    TechnologyDefinition("NestJS", "backend", package_names=["@nestjs/core"]),
    TechnologyDefinition("Spring Boot", "backend", package_names=["spring-boot-starter", "org.springframework.boot"]),
    TechnologyDefinition("ASP.NET", "backend", package_names=["Microsoft.AspNetCore.App", "Microsoft.AspNetCore"]),
    TechnologyDefinition("Laravel", "backend", package_names=["laravel/framework"]),
    TechnologyDefinition("Rails", "backend", package_names=["rails"]),

    # Databases
    TechnologyDefinition("PostgreSQL", "database", package_names=["pg", "psycopg2", "psycopg", "postgresql", "psycopg2-binary", "asyncpg"]),
    TechnologyDefinition("MySQL", "database", package_names=["mysql", "mysql2", "mysqlclient", "pymysql"]),
    TechnologyDefinition("MongoDB", "database", package_names=["mongodb", "mongoose", "pymongo"]),
    TechnologyDefinition("Redis", "database", package_names=["redis", "ioredis", "aioredis"]),
    TechnologyDefinition("SQLite", "database", package_names=["sqlite3", "aiosqlite"]),
    TechnologyDefinition("Cassandra", "database", package_names=["cassandra-driver"]),

    # Infrastructure
    TechnologyDefinition("Docker", "infrastructure", manifest_files=["Dockerfile", "Dockerfile.dev"]),
    TechnologyDefinition("Docker Compose", "infrastructure", manifest_files=["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]),
    TechnologyDefinition("Kubernetes", "infrastructure", config_signatures=["apiVersion: apps/v1", "apiVersion: v1", "kind: Deployment", "kind: Service"]),
    TechnologyDefinition("Nginx", "infrastructure", manifest_files=["nginx.conf", "default.conf"]),
    TechnologyDefinition("Kafka", "infrastructure", package_names=["kafka-node", "confluent-kafka", "kafkajs"]),
    TechnologyDefinition("RabbitMQ", "infrastructure", package_names=["amqplib", "pika"]),
]
