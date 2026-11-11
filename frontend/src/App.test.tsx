import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, ApiError } from "./api";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: {
      me: vi.fn(), teacher: vi.fn(), student: vi.fn(), logout: vi.fn(),
      tasks: vi.fn(), students: vi.fn(), createStudent: vi.fn(),
      issueLink: vi.fn(), revokeLink: vi.fn(), lessons: vi.fn(), pipelines: vi.fn(), runs: vi.fn(),
      teacherResults: vi.fn(), studentResults: vi.fn(),
    },
  };
});

const teacher = { id: "teacher", name: "Демо", role: "teacher" } as const;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.tasks).mockResolvedValue([]);
  vi.mocked(api.students).mockResolvedValue([]);
  vi.mocked(api.lessons).mockResolvedValue([]);
  vi.mocked(api.pipelines).mockResolvedValue([]);
  vi.mocked(api.runs).mockResolvedValue([]);
  vi.mocked(api.teacherResults).mockResolvedValue([]);
  vi.mocked(api.studentResults).mockResolvedValue([]);
});

afterEach(cleanup);

describe("Вход", () => {
  it("показывает отказ и позволяет снова войти", async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError(401, "войдите в платформу"));
    vi.mocked(api.teacher)
      .mockRejectedValueOnce(new ApiError(401, "неверная почта или пароль"))
      .mockResolvedValueOnce(teacher);
    render(<App link={null} />);

    async function submit() {
      fireEvent.change(await screen.findByLabelText("Почта"), { target: { value: "a@example.test" } });
      fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "выдуманный пароль" } });
      fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    }

    await submit();
    expect((await screen.findByRole("alert")).textContent).toBe("неверная почта или пароль");
    await submit();
    await screen.findByText("Вы вошли как Демо.");
    await screen.findByText("В банке пока нет задач.");
    expect(api.teacher).toHaveBeenCalledWith("a@example.test", "выдуманный пароль");
  });

  it("открывает ученический экран по ссылке", async () => {
    vi.mocked(api.student).mockResolvedValue({ id: "student", name: "Сова", role: "student" });
    render(<App link="личный-токен" />);
    await screen.findByText("Вы вошли как Сова.");
    expect(api.student).toHaveBeenCalledWith("личный-токен");
    expect(screen.queryByRole("heading", { name: "Ученики" })).toBeNull();
  });
  it("сохраняет действующий кабинет при отказе по ученической ссылке", async () => {
    vi.mocked(api.student).mockRejectedValue(new ApiError(401, "ссылка недействительна"));
    vi.mocked(api.me).mockResolvedValue(teacher);
    render(<App link="старая-ссылка" />);

    expect((await screen.findByRole("alert")).textContent).toBe("ссылка недействительна");
    await screen.findByText("Вы вошли как Демо.");
  });

  it("обновляет кабинет после смены сеанса в соседней вкладке", async () => {
    const other = { ...teacher, id: "other", name: "Другой преподаватель" };
    vi.mocked(api.me).mockResolvedValueOnce(teacher).mockResolvedValueOnce(other);
    vi.mocked(api.students).mockResolvedValueOnce([{ id: "student", name: "Сова", link_expires_at: null }]);
    render(<App link={null} />);
    await screen.findByText("Сова");

    fireEvent(window, new StorageEvent("storage", { key: "platform-session-change" }));
    await screen.findByText("Вы вошли как Другой преподаватель.");
    await waitFor(() => expect(api.students).toHaveBeenCalledWith("other"));
    expect(screen.queryByText("Сова")).toBeNull();
  });

  it("перепроверяет сеанс после одновременного входа в двух вкладках", async () => {
    const other = { ...teacher, id: "other", name: "Другой преподаватель" };
    vi.mocked(api.me)
      .mockRejectedValueOnce(new ApiError(401, "войдите в платформу"))
      .mockResolvedValueOnce(other)
      .mockResolvedValueOnce(teacher);
    let finish!: (value: typeof teacher) => void;
    vi.mocked(api.teacher).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<App link={null} />);

    fireEvent.change(await screen.findByLabelText("Почта"), { target: { value: "a@example.test" } });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "выдуманный пароль" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    fireEvent(window, new StorageEvent("storage", { key: "platform-session-change" }));
    await screen.findByText("Вы вошли как Другой преподаватель.");

    finish(teacher);
    await screen.findByText("Вы вошли как Демо.");
    expect(api.me).toHaveBeenCalledTimes(3);
  });

  it("убирает кабинет после истечения сеанса при возврате во вкладку", async () => {
    vi.mocked(api.me).mockResolvedValueOnce(teacher)
      .mockRejectedValueOnce(new ApiError(401, "войдите в платформу"));
    render(<App link={null} />);
    await screen.findByText("Вы вошли как Демо.");

    fireEvent(window, new Event("focus"));
    await screen.findByRole("heading", { name: "Вход преподавателя" });
    expect(screen.queryByRole("heading", { name: "Ученики" })).toBeNull();
  });
});

describe("Личные ссылки", () => {
  it("показывает выпущенную ссылку и убирает после отзыва", async () => {
    vi.mocked(api.me).mockResolvedValue(teacher);
    vi.mocked(api.students).mockResolvedValue([{ id: "student", name: "Сова", link_expires_at: null }]);
    vi.mocked(api.issueLink).mockResolvedValue({ token: "secret", expires_at: "2026-12-10T00:00:00Z" });
    vi.mocked(api.revokeLink).mockResolvedValue(undefined);
    render(<App link={null} />);

    fireEvent.click(await screen.findByRole("button", { name: "Выпустить ссылку" }));
    const input = await screen.findByLabelText<HTMLInputElement>("Личная ссылка");
    expect(new URL(input.value).hash).toBe("#student=secret");
    expect(api.issueLink).toHaveBeenCalledWith("teacher", "student");

    fireEvent.click(screen.getByRole("button", { name: "Отозвать ссылку" }));
    await waitFor(() => expect(screen.queryByLabelText("Личная ссылка")).toBeNull());
    expect(api.revokeLink).toHaveBeenCalledWith("teacher", "student");
  });
});
