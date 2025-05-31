from sqlalchemy import Column, Integer, String, Date
from db_config import Base

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String)
    agent_name = Column(String, index=True)
    email = Column(String)
    gender = Column(String)
    batch = Column(String)
    skill = Column(String)
    seniority = Column(String)
    team_leader = Column(String)
    date = Column(Date, index=True)
    shift = Column(String)
