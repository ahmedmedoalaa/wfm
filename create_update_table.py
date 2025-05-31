from sqlalchemy import Table, MetaData
from db_config import engine  # your existing DB engine from db_config.py

def create_schedules_update_table():
    metadata = MetaData()
    metadata.reflect(bind=engine)
    
    if 'schedules_update' not in metadata.tables:
        schedules = metadata.tables['schedules']
        schedules_update = Table(
            'schedules_update', metadata,
            *[c.copy() for c in schedules.columns]
        )
        schedules_update.create(bind=engine)
        print("schedules_update table created.")
    else:
        print("schedules_update table already exists.")

if __name__ == "__main__":
    create_schedules_update_table()
