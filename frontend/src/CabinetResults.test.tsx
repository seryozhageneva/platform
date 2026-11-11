import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { CabinetResults } from "./CabinetResults";

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  api: { teacherResults: vi.fn(), studentResults: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const when = "2026-11-11T10:00:00Z";
const file = { id: "f/1", name: "Материалы.xml", kind: "other", media_type: "application/xml", size: 10 };

it("показывает преподавателю конспект, адресата и ссылку на файл", async () => {
  vi.mocked(api.teacherResults).mockResolvedValue([
    {
      id: "1", run_id: "run", title: "Конспект лекции", created_at: when, student_id: null, student_name: null,
      content: { summary: "Дробь — часть целого.", key_concepts: ["числитель", "знаменатель"] },
    },
    { id: "2", run_id: "run", title: "Итог урока", created_at: when, student_id: "owl", student_name: "Сова", content: "Решено 3 из 4" },
    { id: "3", run_id: "run", title: "Файл «Материалы.xml»", created_at: when, student_id: null, student_name: null, content: { file } },
  ]);

  render(<CabinetResults accountId="teacher" who="teacher" onSessionChange={vi.fn()} />);

  expect(await screen.findByText("Дробь — часть целого.")).toBeTruthy();
  expect(screen.getByText("Конспект")).toBeTruthy();
  expect(screen.getByText("знаменатель")).toBeTruthy();
  expect(screen.getByText(/для ученика Сова/)).toBeTruthy();
  expect(screen.getByText("Решено 3 из 4")).toBeTruthy();
  const link = screen.getByRole("link", { name: "Скачать Материалы.xml" });
  expect(link.getAttribute("href")).toBe("/api/v1/files/f%2F1/content");
  expect(api.teacherResults).toHaveBeenCalledWith("teacher");
});

it("ученику показывает свои результаты без ссылки на файл", async () => {
  vi.mocked(api.studentResults).mockResolvedValue([
    { id: "1", title: "Файл", created_at: when, content: { file } },
  ]);
  render(<CabinetResults accountId="owl" who="student" onSessionChange={vi.fn()} />);
  expect(await screen.findByText("Файл: Материалы.xml")).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByRole("heading", { name: "Мои результаты" })).toBeTruthy();
});

it("сообщает, что результатов нет, и отдаёт смену сеанса наверх", async () => {
  vi.mocked(api.studentResults).mockResolvedValue([]);
  render(<CabinetResults accountId="owl" who="student" onSessionChange={vi.fn()} />);
  expect(await screen.findByText("Результатов пока нет.")).toBeTruthy();
  cleanup();

  const onSessionChange = vi.fn();
  vi.mocked(api.teacherResults).mockRejectedValue(new ApiError(409, "учётная запись сменилась"));
  render(<CabinetResults accountId="teacher" who="teacher" onSessionChange={onSessionChange} />);
  await vi.waitFor(() => expect(onSessionChange).toHaveBeenCalled());
});
