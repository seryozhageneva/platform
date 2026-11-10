import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import type { LessonState } from "./api";
import { StudentHome } from "./StudentHome";

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  api: { lessons: vi.fn(), openLesson: vi.fn(), respondToLesson: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("показывает урок, перечитывает подсказку после конфликта и отправляет формулу", async () => {
  const first: NonNullable<LessonState["screen"]> = {
    revision: "1", task_id: "task", node_id: "show", statement: "Сократите дробь 4/8.",
    forms: ["text", "formula"], can_ask_hint: true,
  };
  const hinted: LessonState = {
    status: "waiting",
    screen: { ...first, revision: "2", hint: { task_id: "task", text: "Найдите общий делитель.", level: 1 } },
  };
  vi.mocked(api.lessons).mockResolvedValue([{ id: "lesson", name: "Дроби" }]);
  vi.mocked(api.openLesson).mockResolvedValueOnce({ status: "waiting", screen: first }).mockResolvedValueOnce(hinted);
  vi.mocked(api.respondToLesson)
    .mockRejectedValueOnce(new ApiError(409, "экран изменился"))
    .mockResolvedValueOnce({ status: "done" });

  render(<StudentHome accountId="student" onSessionChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Дроби" }));
  await screen.findByText(first.statement);
  fireEvent.click(screen.getByRole("button", { name: "Попросить подсказку" }));
  await screen.findByText("Найдите общий делитель.");
  expect(api.respondToLesson).toHaveBeenNthCalledWith(1, "student", "lesson", {
    node_id: "show", revision: "1", response: { action: "hint" },
  });
  expect(api.openLesson).toHaveBeenCalledTimes(2);

  fireEvent.change(screen.getByLabelText("Форма ответа"), { target: { value: "formula" } });
  fireEvent.change(screen.getByLabelText("Формула"), { target: { value: "2/4" } });
  fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
  await screen.findByText("Урок завершён.");
  expect(api.respondToLesson).toHaveBeenNthCalledWith(2, "student", "lesson", {
    node_id: "show", revision: "2",
    response: { action: "answer", answer: { task_id: "task", form: "formula", text: "2/4" } },
  });
});
