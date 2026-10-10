import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:dev@localhost:5432/followit")
LAB_KEY = os.environ.get("LAB_KEY", "dev-lab-key")

S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_BUCKET = os.environ.get("S3_BUCKET", "followit-trails")
S3_KEY = os.environ.get("S3_KEY")
S3_SECRET = os.environ.get("S3_SECRET")

# Constants from contracts/CONTRACT.md
DURATION_MS = 3000
TOKEN_TTL_S = 120
CHALLENGE_TTL_S = 120
POW_TTL_S = 120
POW_BITS = int(os.environ.get("POW_BITS", "18"))  # drop to 16 if a real phone takes > 4 s
CHALLENGES_PER_MIN = 10
ATTEMPTS_PER_CHALLENGE = 5
RESERVATIONS_PER_SESSION = 2
IP_PER_MIN = 300
