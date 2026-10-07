# THO NHANH API

REST API backend for **THO NHANH**, a home repair services platform that connects customers with nearby repair workers.

Built with **FastAPI**, **SQLAlchemy** and **PostgreSQL/PostGIS**, containerized with **Docker Compose**.

## Features

- **Nearby worker search**: finds nearby workers using PostGIS spatial queries (GiST index, KNN).
- **Authentication**: JWT (Bearer header or HTTP-only cookie) with role-based access control (`customer`, `worker`, `admin`).
- **Admin APIs**: manage orders, service catalog, reviews, complaints and dashboard statistics.
- **Worker app APIs**: endpoints for the worker mobile/web client.

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Language   | Python 3.12                         |
| Framework  | FastAPI, Pydantic                   |
| ORM        | SQLAlchemy 2                        |
| Database   | PostgreSQL 16 + PostGIS 3.4         |
| Auth       | PyJWT, bcrypt                       |
| DevOps     | Docker, Docker Compose              |

## Project Structure

```
.
├── app/
│   ├── controllers/   # Request handling logic
│   ├── routes/        # API routers (mounted under /api/v1)
│   ├── services/      # Business logic (geo search)
│   ├── models/        # SQLAlchemy models
│   ├── schemas/       # Pydantic request/response schemas
│   ├── middleware/    # Auth (JWT, RBAC), CORS
│   ├── utils/         # Security, pagination, responses
│   ├── config.py      # Settings loaded from .env
│   └── main.py        # App entry point
├── db/schema.sql      # Database schema (auto-loaded by Docker)
├── scripts/           # Admin & demo data scripts
├── Dockerfile
└── docker-compose.yml
```

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

### 1. Clone the repository

```bash
git clone https://github.com/archuser-q/<repo-name>.git
cd <repo-name>
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env` and set real values:

| Variable            | Description                                  |
|---------------------|----------------------------------------------|
| `POSTGRES_USER`     | Database user                                |
| `POSTGRES_PASSWORD` | Database password                            |
| `POSTGRES_DB`       | Database name                                |
| `JWT_SECRET`        | Secret key for signing JWT tokens (required) |
| `CORS_ORIGINS`      | Allowed frontend origins (JSON list)         |
| `DEBUG`             | `true` / `false`                             |

> `.env` is git-ignored. Never commit real credentials.

### 3. Run

```bash
docker compose up -d --build
```

On first run, `db/schema.sql` is loaded automatically into the database.

### 4. Open the API docs

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## Useful Commands

```bash
# Create an admin account
docker compose exec api python -m scripts.create_admin

# Seed demo locations for approved workers (around Hoan Kiem, Hanoi)
docker compose exec api python -m scripts.seed_worker_locations

# View API logs
docker compose logs -f api

# Stop containers
docker compose down

# Stop and wipe the database (re-runs schema.sql on next start)
docker compose down -v
```

## Nearby Worker Search

Uses PostGIS `ST_DWithin` and KNN ordering (`<->`) on a GiST index to find approved, online workers offering the requested service within the search radius, sorted by distance.