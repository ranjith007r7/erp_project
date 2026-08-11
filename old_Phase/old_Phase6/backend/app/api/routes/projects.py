from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.projects import Project, Task, TimeLog
from app.schemas.projects import (
    ProjectCreate, ProjectOut, ProjectStatusUpdate,
    TaskCreate, TaskOut, TaskStatusUpdate,
    TimeLogCreate, TimeLogOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(get_current_user)])


# ---------------- Projects ----------------
@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    project = Project(org_id=org_id, **payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Project).filter(Project.org_id == org_id).all()


@router.patch("/{project_id}/status", response_model=ProjectOut)
def update_project_status(project_id: str, payload: ProjectStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    project = db.query(Project).filter(Project.id == project_id, Project.org_id == org_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = payload.status
    db.commit()
    db.refresh(project)
    return project


# ---------------- Tasks ----------------
@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    project = db.query(Project).filter(Project.id == payload.project_id, Project.org_id == org_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Project.org_id == org_id)
        .all()
    )


@router.patch("/tasks/{task_id}/status", response_model=TaskOut)
def update_task_status(task_id: str, payload: TaskStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    task = (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.id == task_id, Project.org_id == org_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = payload.status
    db.commit()
    db.refresh(task)
    return task


# ---------------- Time Logs ----------------
@router.post("/time-logs", response_model=TimeLogOut, status_code=201)
def create_time_log(payload: TimeLogCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id),
                     current_user=Depends(get_current_user)):
    task = (
        db.query(Task)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.id == payload.task_id, Project.org_id == org_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    log = TimeLog(task_id=payload.task_id, user_id=current_user.id, hours=payload.hours, date=payload.date)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get("/time-logs", response_model=list[TimeLogOut])
def list_time_logs(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(TimeLog)
        .join(Task, Task.id == TimeLog.task_id)
        .join(Project, Project.id == Task.project_id)
        .filter(Project.org_id == org_id)
        .all()
    )
