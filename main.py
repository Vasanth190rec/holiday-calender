import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://portal:localpassword@db:5432/holiday_calendar")
SECRET_KEY = os.getenv("SECRET_KEY", "")
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_DISPLAY_NAME = os.getenv("ADMIN_DISPLAY_NAME", "Calendar Administrator")

if not SECRET_KEY or len(SECRET_KEY) < 32:
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters in production.")
    SECRET_KEY = "local-development-only-change-this-secret-key-32chars"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Holiday(Base):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if not user or not user.active:
        request.session.clear()
        return None
    return user

def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user

def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator permission required.")
    return user

def create_admin_if_configured(db: Session):
    if not ADMIN_PASSWORD:
        return
    existing = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
    if existing:
        return
    if len(ADMIN_PASSWORD) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters when bootstrapping the admin.")
    db.add(User(username=ADMIN_USERNAME, display_name=ADMIN_DISPLAY_NAME,
                password_hash=pwd_context.hash(ADMIN_PASSWORD), is_admin=True))
    db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        create_admin_if_configured(db)
    yield

app = FastAPI(title="Holiday Calendar", version="1.0.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="holiday_session",
                   same_site="lax", https_only=SESSION_HTTPS_ONLY, max_age=60 * 60 * 8)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def page(request: Request, name: str, **context):
    response_status = context.pop("status_code", 200)
    return templates.TemplateResponse(request=request, name=name, context=context, status_code=response_status)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: Optional[User] = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    try:
        year = int(request.query_params.get("year", today.year))
        month = int(request.query_params.get("month", today.month))
        if year < 1900 or year > 2200 or month < 1 or month > 12:
            raise ValueError()
    except ValueError:
        year, month = today.year, today.month
    month_start = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    month_end = next_month - timedelta(days=1)
    holidays = db.scalars(select(Holiday).where(
        Holiday.holiday_date >= month_start,
        Holiday.holiday_date <= month_end
    ).order_by(Holiday.holiday_date)).all()
    return page(request, "calendar.html", user=user, holidays=holidays, year=year, month=month,
                today=today, days_in_month=month_end.day, first_weekday=month_start.weekday())

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: Optional[User] = Depends(current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return page(request, "login.html", user=None, error=None)

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not user.active or not pwd_context.verify(password, user.password_hash):
        return page(request, "login.html", user=None, error="Invalid username or password.", status_code=401)
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/holidays/new", response_class=HTMLResponse)
def new_holiday_page(request: Request, user: User = Depends(require_admin)):
    return page(request, "holiday_form.html", user=user, holiday=None, error=None)

@app.post("/holidays/new")
def create_holiday(request: Request, holiday_date: date = Form(...), title: str = Form(...),
                    description: str = Form(""), user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    title = title.strip()
    if not title or len(title) > 160 or len(description) > 5000:
        return page(request, "holiday_form.html", user=user, holiday=None,
                    error="Title is required (max 160 characters); description must be 5,000 characters or fewer.", status_code=422)
    if db.scalar(select(Holiday).where(Holiday.holiday_date == holiday_date)):
        return page(request, "holiday_form.html", user=user, holiday=None,
                    error="A holiday already exists on this date. Edit that entry instead.", status_code=409)
    db.add(Holiday(holiday_date=holiday_date, title=title, description=description.strip()))
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/holidays/{holiday_id}/edit", response_class=HTMLResponse)
def edit_holiday_page(holiday_id: int, request: Request, user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    holiday = db.get(Holiday, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found.")
    return page(request, "holiday_form.html", user=user, holiday=holiday, error=None)

@app.post("/holidays/{holiday_id}/edit")
def edit_holiday(holiday_id: int, request: Request, holiday_date: date = Form(...), title: str = Form(...),
                 description: str = Form(""), user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    holiday = db.get(Holiday, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found.")
    title = title.strip()
    if not title or len(title) > 160 or len(description) > 5000:
        return page(request, "holiday_form.html", user=user, holiday=holiday,
                    error="Title is required (max 160 characters); description must be 5,000 characters or fewer.", status_code=422)
    conflict = db.scalar(select(Holiday).where(Holiday.holiday_date == holiday_date, Holiday.id != holiday_id))
    if conflict:
        return page(request, "holiday_form.html", user=user, holiday=holiday,
                    error="Another holiday already exists on that date.", status_code=409)
    holiday.holiday_date = holiday_date
    holiday.title = title
    holiday.description = description.strip()
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/holidays/{holiday_id}/delete")
def delete_holiday(holiday_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    holiday = db.get(Holiday, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found.")
    db.delete(holiday)
    db.commit()
    return RedirectResponse("/", status_code=303)
