from db_config import Base, engine
from models import Schedule

Base.metadata.create_all(bind=engine)
print("Database initialized.")
