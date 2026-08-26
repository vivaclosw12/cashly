
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Numeric, Text, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./data/cashly.db")
connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {}
engine=create_engine(DATABASE_URL,connect_args=connect_args,future=True)
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False,future=True)
Base=declarative_base()

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__="users"
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    email=Column(String(255),unique=True,index=True,nullable=False)
    password_hash=Column(String(255),nullable=False)
    is_active=Column(Boolean,default=True)
    created_at=Column(DateTime(timezone=True),default=now)

class Merchant(Base):
    __tablename__="merchants"
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    slug=Column(String(80),unique=True,index=True,nullable=False)
    category=Column(String(80),nullable=False)
    cashback_label=Column(String(80),nullable=False)
    logo_text=Column(String(8),nullable=False)
    status=Column(String(30),default="active")

class Click(Base):
    __tablename__="clicks"
    id=Column(Integer,primary_key=True)
    click_id=Column(String(80),unique=True,index=True,nullable=False)
    user_id=Column(Integer,ForeignKey("users.id"),index=True,nullable=False)
    merchant_id=Column(Integer,ForeignKey("merchants.id"),index=True,nullable=False)
    source_url=Column(Text)
    clean_url=Column(Text,nullable=False)
    affiliate_url=Column(Text,nullable=False)
    sub_id=Column(String(160),unique=True,index=True,nullable=False)
    created_at=Column(DateTime(timezone=True),default=now)

class Conversion(Base):
    __tablename__="conversions"
    __table_args__=(UniqueConstraint("merchant_id","order_id",name="uq_merchant_order"),)
    id=Column(Integer,primary_key=True)
    merchant_id=Column(Integer,ForeignKey("merchants.id"),nullable=False)
    click_id=Column(String(80),index=True,nullable=False)
    sub_id=Column(String(160),index=True,nullable=True)
    order_id=Column(String(160),nullable=False)
    order_amount=Column(Numeric(18,2),nullable=False)
    commission_amount=Column(Numeric(18,2),nullable=False)
    cashback_amount=Column(Numeric(18,2),nullable=False)
    platform_revenue=Column(Numeric(18,2),nullable=False)
    status=Column(String(30),default="pending")
    source=Column(String(60),default="manual")
    created_at=Column(DateTime(timezone=True),default=now)
    updated_at=Column(DateTime(timezone=True),default=now)

class Ledger(Base):
    __tablename__="ledger"
    id=Column(Integer,primary_key=True)
    user_id=Column(Integer,ForeignKey("users.id"),index=True,nullable=False)
    entry_type=Column(String(40),nullable=False)
    amount=Column(Numeric(18,2),nullable=False)
    reference=Column(String(160),nullable=False)
    note=Column(String(255))
    created_at=Column(DateTime(timezone=True),default=now)

class Withdrawal(Base):
    __tablename__="withdrawals"
    id=Column(Integer,primary_key=True)
    user_id=Column(Integer,ForeignKey("users.id"),index=True,nullable=False)
    amount=Column(Numeric(18,2),nullable=False)
    destination=Column(String(255),nullable=False)
    status=Column(String(30),default="pending")
    created_at=Column(DateTime(timezone=True),default=now)

Base.metadata.create_all(engine)

def seed():
    with SessionLocal() as db:
        if db.query(Merchant).count()==0:
            db.add_all([
                Merchant(name="Shopee",slug="shopee",category="Marketplace",cashback_label="Up to 8%",logo_text="S"),
                Merchant(name="Lazada",slug="lazada",category="Marketplace",cashback_label="Up to 7%",logo_text="L"),
                Merchant(name="Travel",slug="travel",category="Travel",cashback_label="Up to 10%",logo_text="T"),
                Merchant(name="Food",slug="food",category="Food",cashback_label="Up to 12%",logo_text="F"),
            ])
            db.commit()
seed()
