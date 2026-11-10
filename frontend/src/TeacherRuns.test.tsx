import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import type { RunSummary } from "./api";
import { TeacherRuns } from "./TeacherRuns";

const time = "2026-11-10T12:00:00Z";
const pipeline = {
  id: "pipeline", slug: "demo", name: "Тренировка", latest_version: 3,
  created_at: time, updated_at: time,
};
const session = { accountId: "teacher", onSessionChange: vi.fn() };
const result = {
  id: "manual", pipeline_id: pipeline.id, pipeline_version: 3, params: {}, status: "error" as const,
  current: ["check"], waiting: [], error: "Ошибка блока",
};

function summary(id: string, pipeline_name: string, changes: Partial<RunSummary> = {}): RunSummary {
  return {
    id, pipeline_id: pipeline.id, pipeline_name, pipeline_version: 3, student_name: null,
    status: "done", current: [], waiting: [], error: null, updated_at: time, ...changes,
  };
}

function withTrigger(type: "manual" | "student"): Awaited<ReturnType<typeof api.pipeline>> {
  return {
    ...pipeline,
    graph: {
      format: 1 as const, id: "demo", name: pipeline.name, description: "",
      nodes: [{ id: "start", type: "trigger" as const, title: "Старт", launches: [{ type, settings: {} }] }],
      transitions: [],
      params: [
        { name: "topic", title: "Тема", type: "string" as const },
        { name: "count", title: "Число задач", type: "integer" as const, default: 3 },
        { name: "weight", title: "Вес", type: "number" as const, default: 0.5 },
        { name: "hints", title: "Подсказки", type: "boolean" as const, default: false },
      ],
    },
  };
}

beforeEach(() => {
  vi.spyOn(api, "runs").mockResolvedValue([]);
  vi.spyOn(api, "pipelines").mockResolvedValue([pipeline]);
  vi.spyOn(api, "pipeline").mockResolvedValue(withTrigger("manual"));
  vi.spyOn(api, "run").mockResolvedValue(result);
  vi.spyOn(api, "runEvents").mockResolvedValue([
    { id: 2, node_id: "start", type: "run_started", data: {}, created_at: time },
    { id: 3, node_id: "check", type: "node_failed", data: {}, created_at: time },
  ]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("показывает очередь преподавателя, журнал выбранного запуска и актуальный статус после обновления", async () => {
  const student = summary("lesson", "Урок", {
    status: "waiting", student_name: "Сова", current: ["answer"],
    waiting: [{ node_id: "answer", who: "student" }],
  });
  const approval = summary("review", "Материалы", {
    status: "waiting", waiting: [{ node_id: "review", who: "teacher" }],
  });
  vi.mocked(api.runs).mockResolvedValueOnce([student, approval])
    .mockResolvedValueOnce([student, { ...approval, status: "done", waiting: [] }]);
  render(<TeacherRuns {...session} />);

  const queue = within(await screen.findByRole("region", { name: "Очередь подтверждений" }));
  expect(queue.queryByRole("button", { name: "Урок" })).toBeNull();
  expect(screen.getByText(/Сова/)).toBeTruthy();
  expect(screen.getByText("answer · ждёт ученика")).toBeTruthy();
  fireEvent.click(queue.getByRole("button", { name: "Материалы" }));

  const journal = within(screen.getByRole("region", { name: "Журнал запуска" }));
  await journal.findByText(/Ошибка на шаге/);
  expect(journal.getAllByRole("listitem").map((event) => event.textContent)).toEqual([
    expect.stringContaining("start · Запуск начался"),
    expect.stringContaining("check · Ошибка на шаге"),
  ]);
  expect(api.runEvents).toHaveBeenCalledWith("teacher", "review");

  fireEvent.click(screen.getByRole("button", { name: "Обновить запуски" }));
  await queue.findByText("Нет запусков на подтверждении.");
});

it("запускает с типизированными параметрами один раз и открывает журнал ошибки", async () => {
  let finish: (run: typeof result) => void = () => {};
  const launch = vi.spyOn(api, "launchRun").mockImplementation(() =>
    new Promise((resolve) => { finish = resolve; }));
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  const topic = await screen.findByLabelText("Тема");
  fireEvent.change(topic, { target: { value: "Дроби" } });
  expect((screen.getByLabelText("Число задач") as HTMLInputElement).step).toBe("1");
  expect((screen.getByLabelText("Вес") as HTMLInputElement).step).toBe("any");
  fireEvent.change(screen.getByLabelText("Вес"), { target: { value: "1.25" } });
  fireEvent.change(screen.getByLabelText("Подсказки"), { target: { value: "true" } });

  const button = screen.getByRole<HTMLButtonElement>("button", { name: "Запустить" });
  fireEvent.click(button);
  expect(button.matches(":disabled")).toBe(true);
  fireEvent.submit(button.form!);
  expect(launch).toHaveBeenCalledTimes(1);
  expect(launch).toHaveBeenCalledWith("teacher", pipeline.id, {
    expected_version: 3, params: { topic: "Дроби", weight: 1.25, hints: true },
  });

  await act(async () => finish(result));
  const journal = within(await screen.findByRole("region", { name: "Журнал запуска" }));
  await journal.findByText("Ошибка блока");
  expect(api.runEvents).toHaveBeenCalledWith("teacher", "manual");
  expect(api.runs).toHaveBeenCalledTimes(2);
});

it("при потере ответа обновляет список, сохраняет форму и требует явно разрешить повтор", async () => {
  const launch = vi.spyOn(api, "launchRun").mockRejectedValue(new TypeError("connection lost"));
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  const topic = await screen.findByLabelText<HTMLInputElement>("Тема");
  fireEvent.change(topic, { target: { value: "Дроби" } });
  const button = screen.getByRole<HTMLButtonElement>("button", { name: "Запустить" });
  fireEvent.click(button);

  expect((await screen.findByRole("alert")).textContent).toContain("Запуск мог состояться");
  expect(api.runs).toHaveBeenCalledTimes(2);
  expect(topic.value).toBe("Дроби");
  expect(button.disabled).toBe(true);
  fireEvent.submit(button.form!);
  expect(launch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Разрешить повторный запуск" }));
  expect(button.disabled).toBe(false);
});

it.each(["Число задач", "Вес"])("защищает от округления большого целого в поле «%s»", async (label) => {
  const launch = vi.spyOn(api, "launchRun");
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  const input = await screen.findByLabelText(label);
  fireEvent.change(input, { target: { value: "9007199254740993" } });
  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  expect((await screen.findByRole("alert")).textContent).toContain("не может точно передать");
  expect(launch).not.toHaveBeenCalled();
});

it("оставляет подстановку большого целого по умолчанию серверу", async () => {
  const detail = withTrigger("manual");
  detail.graph.params = detail.graph.params.map((param) =>
    param.name === "count" ? { ...param, default: Number.MAX_SAFE_INTEGER + 1 } : param);
  vi.mocked(api.pipeline).mockResolvedValue(detail);
  const launch = vi.spyOn(api, "launchRun").mockResolvedValue(result);
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  const input = await screen.findByLabelText<HTMLInputElement>("Число задач");
  expect(input.value).toBe("");
  expect(input.placeholder).toBe("Значение по умолчанию с сервера");

  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  await screen.findByText("Ошибка блока");
  expect(launch).toHaveBeenCalledWith("teacher", pipeline.id, {
    expected_version: 3, params: { topic: "" },
  });
});

it("показывает причины отказа и сохраняет введённые параметры", async () => {
  vi.spyOn(api, "launchRun").mockRejectedValue(new ApiError(422, "Запуск отклонён", [
    { node: "start", code: "bad_param", message: "Проверьте тему" },
  ]));
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  const topic = await screen.findByLabelText<HTMLInputElement>("Тема");
  fireEvent.change(topic, { target: { value: "Дроби" } });
  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));

  expect((await screen.findByRole("alert")).textContent).toContain("start · Проверьте тему");
  expect(topic.value).toBe("Дроби");
  expect(api.runEvents).not.toHaveBeenCalled();
});

it("не предлагает запускать пайплайн, рассчитанный только на учеников", async () => {
  vi.mocked(api.pipeline).mockResolvedValue(withTrigger("student"));
  render(<TeacherRuns {...session} />);
  await screen.findByRole("option", { name: pipeline.name });
  fireEvent.change(screen.getByLabelText("Пайплайн для запуска"), { target: { value: pipeline.id } });
  await screen.findByText("Этот пайплайн нельзя запустить вручную.");
  expect(screen.queryByRole("button", { name: "Запустить" })).toBeNull();
});

it("сохраняет правку при ошибке и обновляет очередь и журнал после решения", async () => {
  const approval = summary("review", "Материалы", {
    status: "waiting", current: ["review"], waiting: [{ node_id: "review", who: "teacher" }],
  });
  const paused: Awaited<ReturnType<typeof api.run>> = {
    ...result, id: "review", error: null, status: "waiting", current: ["review"],
    waiting: [{
      node_id: "review", who: "teacher", screen: "review_table", approval_id: "pause",
      data: {
        columns: [{ key: "/id", title: "Код" }, { key: "/comment", title: "Комментарий", editable: true }],
        rows: [{ "/id": "A", "/comment": "Черновик" }, { "/id": "B", "/comment": "Пропустить" }],
      },
    }],
  };
  const finished = { ...paused, status: "done" as const, current: [], waiting: [] };
  vi.mocked(api.runs).mockResolvedValueOnce([approval])
    .mockResolvedValueOnce([{ ...approval, status: "done", waiting: [] }]);
  vi.mocked(api.run).mockResolvedValueOnce(paused).mockResolvedValueOnce(finished);
  vi.mocked(api.runEvents).mockResolvedValueOnce([]).mockResolvedValueOnce([{
    id: 3, node_id: "review", type: "approval_decided", created_at: time,
    data: { outcome: "approved", kept: 1, changed: 1, skipped: 1 },
  }]);
  const respond = vi.spyOn(api, "respondToRun")
    .mockRejectedValueOnce(new ApiError(422, "Проверьте правки."))
    .mockResolvedValueOnce(finished);

  render(<TeacherRuns {...session} />);
  const queue = within(await screen.findByRole("region", { name: "Очередь подтверждений" }));
  fireEvent.click(await queue.findByRole("button", { name: "Материалы" }));
  const journal = within(screen.getByRole("region", { name: "Журнал запуска" }));
  const form = within(await journal.findByRole("form", { name: "Таблица подтверждения" }));
  const field = form.getByRole<HTMLTextAreaElement>("textbox", { name: "Комментарий, строка 1" });
  fireEvent.change(field, { target: { value: "Исправлено" } });
  fireEvent.click(form.getByRole("checkbox", { name: "Пропустить строку 2" }));
  expect(form.getByText("Строк пойдёт дальше: 1 из 2.")).toBeTruthy();

  const submit = form.getByRole<HTMLButtonElement>("button", { name: "Подтвердить" });
  fireEvent.click(submit);
  expect(submit.matches(":disabled")).toBe(true);
  fireEvent.submit(submit.form!);
  expect(respond).toHaveBeenCalledTimes(1);
  await form.findByText("Проверьте правки.");
  expect(field.value).toBe("Исправлено");

  fireEvent.click(submit);
  expect(respond).toHaveBeenLastCalledWith("teacher", "review", {
    node_id: "review", approval_id: "pause",
    response: { rows: [
      { index: 0, keep: true, values: { "/comment": "Исправлено" } },
      { index: 1, keep: false, values: {} },
    ] },
  });
  await queue.findByText("Нет запусков на подтверждении.");
  await journal.findByText(/Оставлено 1, исправлено 1, пропущено 1/);
  expect(journal.queryByRole("form", { name: "Таблица подтверждения" })).toBeNull();
});

it("показывает ошибку запуска после отправки решения без сообщения об успехе", async () => {
  const approval = summary("review", "Материалы", {
    status: "waiting", waiting: [{ node_id: "review", who: "teacher" }],
  });
  const paused: Awaited<ReturnType<typeof api.run>> = {
    ...result, id: "review", error: null, status: "waiting", waiting: [{
      node_id: "review", who: "teacher", screen: "review_table", approval_id: "pause",
      data: { columns: [{ key: "/text", title: "Текст" }], rows: [{ "/text": "Строка" }] },
    }],
  };
  const failed = { ...result, id: "review" };
  vi.mocked(api.runs).mockResolvedValueOnce([approval]);
  vi.mocked(api.run).mockResolvedValueOnce(paused).mockResolvedValueOnce(failed);
  vi.spyOn(api, "respondToRun").mockResolvedValue(failed);

  render(<TeacherRuns {...session} />);
  const queue = within(await screen.findByRole("region", { name: "Очередь подтверждений" }));
  fireEvent.click(queue.getByRole("button", { name: "Материалы" }));
  const journal = within(screen.getByRole("region", { name: "Журнал запуска" }));
  fireEvent.click(await journal.findByRole("button", { name: "Подтвердить" }));
  await journal.findByText("Запуск остановился с ошибкой. Подробности в журнале.");
  await journal.findByText("Ошибка блока");
  expect(journal.queryByText("Решение принято.")).toBeNull();
});
