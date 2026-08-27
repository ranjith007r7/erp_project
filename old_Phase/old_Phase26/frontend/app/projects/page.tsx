"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";

type Project = { id: string; name: string; status: string };
type Task = { id: string; project_id: string; title: string; status: string; priority: string };
type TimeLog = { task_id: string; hours: string };

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [timeLogs, setTimeLogs] = useState<TimeLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [projectForm, setProjectForm] = useState({ name: "" });
  const [taskForm, setTaskForm] = useState({ project_id: "", title: "", priority: "medium" });
  const [logHours, setLogHours] = useState<Record<string, string>>({});

  function loadAll() {
    apiRequest<Project[]>("/api/projects", { auth: true }).then(setProjects).catch((e) => setError(e.message));
    apiRequest<Task[]>("/api/projects/tasks", { auth: true }).then(setTasks).catch(() => {});
    apiRequest<TimeLog[]>("/api/projects/time-logs", { auth: true }).then(setTimeLogs).catch(() => {});
  }

  useEffect(loadAll, []);

  function hoursFor(taskId: string) {
    return timeLogs.filter((l) => l.task_id === taskId).reduce((sum, l) => sum + Number(l.hours), 0);
  }

  function projectName(id: string) {
    return projects.find((p) => p.id === id)?.name || id.slice(0, 8);
  }

  async function addProject(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/projects", { method: "POST", auth: true, body: projectForm }).catch((err) => setError(err.message));
    setProjectForm({ name: "" });
    loadAll();
  }

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/projects/tasks", { method: "POST", auth: true, body: taskForm });
      setTaskForm({ project_id: taskForm.project_id, title: "", priority: "medium" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add task");
    }
  }

  async function toggleTaskDone(task: Task) {
    const next = task.status === "done" ? "todo" : "done";
    await apiRequest(`/api/projects/tasks/${task.id}/status`, { method: "PATCH", auth: true, body: { status: next } }).catch((err) => setError(err.message));
    loadAll();
  }

  async function logTime(taskId: string) {
    const hours = logHours[taskId];
    if (!hours) return;
    await apiRequest("/api/projects/time-logs", { method: "POST", auth: true, body: { task_id: taskId, hours: Number(hours) } }).catch((err) => setError(err.message));
    setLogHours({ ...logHours, [taskId]: "" });
    loadAll();
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Projects & Tasks" />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <form onSubmit={addProject} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">New Project</h2>
          <input
            placeholder="Project name"
            required
            value={projectForm.name}
            onChange={(e) => setProjectForm({ name: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">
            Create Project
          </button>
        </form>

        <form onSubmit={addTask} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">New Task</h2>
          <select
            required
            value={taskForm.project_id}
            onChange={(e) => setTaskForm({ ...taskForm, project_id: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input
            placeholder="Task title"
            required
            value={taskForm.title}
            onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm"
          />
          <select
            value={taskForm.priority}
            onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })}
            className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
          <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">
            Add Task
          </button>
        </form>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {projects.map((project) => (
          <section key={project.id} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4">
            <h2 className="font-semibold text-slate-800 dark:text-white mb-3">{project.name} <span className="text-xs text-slate-400 dark:text-zinc-500">({project.status})</span></h2>
            <div className="space-y-2">
              {tasks.filter((t) => t.project_id === project.id).map((task) => (
                <div key={task.id} className="border border-slate-200 dark:border-zinc-800 rounded-lg p-2 text-sm">
                  <div className="flex justify-between items-center">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={task.status === "done"} onChange={() => toggleTaskDone(task)} />
                      <span className={task.status === "done" ? "line-through text-slate-400 dark:text-zinc-500" : "text-slate-800 dark:text-white"}>
                        {task.title}
                      </span>
                    </label>
                    <span className="text-xs text-slate-400 dark:text-zinc-500">{task.priority} · {hoursFor(task.id)}h logged</span>
                  </div>
                  <div className="flex gap-2 mt-1">
                    <input
                      type="number"
                      placeholder="Hours"
                      value={logHours[task.id] || ""}
                      onChange={(e) => setLogHours({ ...logHours, [task.id]: e.target.value })}
                      className="w-20 border border-slate-300 dark:border-zinc-700 rounded px-2 py-1 text-xs"
                    />
                    <button
                      onClick={() => logTime(task.id)}
                      className="text-xs bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 px-2 py-1 rounded hover:bg-slate-200 dark:hover:bg-zinc-700"
                    >
                      Log time
                    </button>
                  </div>
                </div>
              ))}
              {tasks.filter((t) => t.project_id === project.id).length === 0 && (
                <p className="text-xs text-slate-400 dark:text-zinc-500">No tasks yet.</p>
              )}
            </div>
          </section>
        ))}
        {projects.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No projects yet.</p>}
      </div>
    </main>
  );
}
