import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { PipelineEditor, TeacherPipelines } from "./PipelineEditor";
import { newPipeline } from "./pipelineGraph";

vi.mock("./PipelineCanvas", () => ({
  PipelineCanvas: ({ issues, select }: { issues: { message: string }[]; select: (id: string) => void }) =>
    <div>
      <button type="button" onClick={() => select("start")}>Старт</button>
      {issues.map((issue) => <p key={issue.message}>{issue.message}</p>)}
    </div>,
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("сохраняет время в графе и открывает панель расписания для сохранённой версии", async () => {
  const save = vi.spyOn(api, "savePipeline").mockResolvedValue({ id: "saved", version: 1, warnings: [] });
  const settings = vi.spyOn(api, "schedule")
    .mockResolvedValue({ enabled: false, cron: "0 18 * * 5", params: {} });
  render(<PipelineEditor initial={{ ...newPipeline(), name: "Сводка" }} catalog={[]} accountId="teacher"
    onSaved={vi.fn()} close={vi.fn()} onSessionChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Старт" }));
  fireEvent.change(screen.getByLabelText("Расписание (cron, время Москвы)"), { target: { value: "0 18 * * 5" } });
  expect(settings).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await screen.findByRole("checkbox", { name: "Включено" });
  expect(save.mock.calls[0]?.[1].nodes[0]).toMatchObject({
    launches: [{ type: "student" }, { type: "schedule", cron: "0 18 * * 5" }],
  });
  expect(settings).toHaveBeenCalledWith("teacher", "saved");
});

it("сохраняет, показывает предупреждение, оставляет правки после отказа и повторяет сохранение той же версии графа", async () => {
  const warning = { node: "start", code: "warning", message: "Предупреждение от сервера" };
  const issue = { node: "start", code: "invalid", message: "Проверьте старт" };
  const save = vi.spyOn(api, "savePipeline")
    .mockResolvedValueOnce({ id: "first", version: 1, warnings: [warning] })
    .mockRejectedValueOnce(new ApiError(422, "Граф не сохранён", [issue]))
    .mockResolvedValueOnce({ id: "first", version: 2, warnings: [] });
  const graph = newPipeline();
  render(<PipelineEditor initial={graph} catalog={[]} accountId="teacher"
    onSaved={vi.fn()} close={vi.fn()} onSessionChange={vi.fn()} />);
  const name = screen.getByLabelText<HTMLInputElement>("Название пайплайна");
  const button = screen.getByRole("button", { name: "Сохранить" });
  fireEvent.change(name, { target: { value: "Дроби" } });
  fireEvent.click(button);
  await screen.findByText("Сохранено. Версия 1.");
  await screen.findByText(/Предупреждение от сервера/);
  expect(save).toHaveBeenNthCalledWith(1, "teacher", { ...graph, name: "Дроби" }, undefined);

  fireEvent.change(name, { target: { value: "Дроби с подсказками" } });
  fireEvent.click(button);
  await screen.findByText("Граф не сохранён");
  await screen.findByText("Проверьте старт");
  expect(name.value).toBe("Дроби с подсказками");
  fireEvent.click(button);
  await screen.findByText("Сохранено. Версия 2.");
  expect(save).toHaveBeenNthCalledWith(3, "teacher", { ...graph, name: "Дроби с подсказками" }, "first");
});

it("открывает из списка последнюю сохранённую версию", async () => {
  const entry = { id: "saved", slug: "lesson", name: "Тренировка", latest_version: 3, created_at: "", updated_at: "" };
  vi.spyOn(api, "pipelines").mockResolvedValue([entry]);
  vi.spyOn(api, "blocks").mockResolvedValue([]);
  const open = vi.spyOn(api, "pipeline").mockResolvedValue({ ...entry, graph: { ...newPipeline(), name: entry.name } });
  render(<TeacherPipelines accountId="teacher" onSessionChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: entry.name }));
  expect((await screen.findByLabelText<HTMLInputElement>("Название пайплайна")).value).toBe(entry.name);
  expect(screen.getByText("Версия 3")).toBeTruthy();
  expect(open).toHaveBeenCalledWith("teacher", entry.id);
});

it("подтверждает выход только при несохранённых изменениях", () => {
  const close = vi.fn();
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<PipelineEditor initial={newPipeline()} catalog={[]} accountId="teacher"
    onSaved={vi.fn()} close={close} onSessionChange={vi.fn()} />);
  const back = screen.getByRole("button", { name: "К списку" });
  fireEvent.click(back);
  expect(close).toHaveBeenCalledTimes(1);
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Название пайплайна"), { target: { value: "Черновик" } });
  fireEvent.click(back);
  expect(close).toHaveBeenCalledTimes(1);
  expect(screen.getByDisplayValue("Черновик")).toBeTruthy();
  fireEvent.click(back);
  expect(close).toHaveBeenCalledTimes(2);
});

it("различает пустое строковое значение параметра и отсутствие значения", async () => {
  const graph = { ...newPipeline(), name: "Урок", params: [{ name: "topic", title: "Тема", type: "string" as const }] };
  const save = vi.spyOn(api, "savePipeline")
    .mockResolvedValueOnce({ id: "first", version: 1, warnings: [] })
    .mockResolvedValueOnce({ id: "first", version: 2, warnings: [] });
  render(<PipelineEditor initial={graph} catalog={[]} accountId="teacher"
    onSaved={vi.fn()} close={vi.fn()} onSessionChange={vi.fn()} />);
  fireEvent.click(screen.getByText("Параметры пайплайна"));
  const button = screen.getByRole("button", { name: "Сохранить" });
  fireEvent.click(screen.getByRole("button", { name: "По умолчанию · задать пустую строку" }));
  fireEvent.click(button);
  await screen.findByText("Сохранено. Версия 1.");
  expect(save.mock.calls[0]?.[1].params[0]?.default).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "По умолчанию · сбросить значение" }));
  fireEvent.click(button);
  await screen.findByText("Сохранено. Версия 2.");
  expect(save.mock.calls[1]?.[1].params[0]?.default).toBeNull();
});

it.each([false, true])("сверяет сохранённую версию перед повтором после обрыва связи (существующий граф: %s)", async (existing) => {
  const graph = { ...newPipeline(), name: "Дроби", params: [{ name: "topic", title: "Тема", type: "string" as const }] };
  const version = existing ? 2 : 1;
  const entry = { id: "saved", slug: graph.id, name: graph.name, latest_version: version, created_at: "", updated_at: "" };
  const list = vi.spyOn(api, "pipelines").mockResolvedValue([entry]);
  const read = vi.spyOn(api, "pipeline").mockResolvedValue({
    ...entry,
    graph: { ...graph, params: [{ name: "topic", title: "Тема", type: "string", default: null }] },
  });
  const save = vi.spyOn(api, "savePipeline").mockRejectedValueOnce(new TypeError("Connection lost"));
  const onSaved = vi.fn();
  render(<PipelineEditor initial={graph} catalog={[]} accountId="teacher"
    id={existing ? entry.id : undefined} version={existing ? 1 : undefined}
    onSaved={onSaved} close={vi.fn()} onSessionChange={vi.fn()} />);
  const button = screen.getByRole("button", { name: "Сохранить" });
  fireEvent.click(button);
  await screen.findByText(/Ответ на сохранение потерян/);
  fireEvent.click(button);
  await screen.findByText(`Сохранение подтверждено. Версия ${version}.`);
  expect(list).toHaveBeenCalledTimes(existing ? 0 : 1);
  expect(read).toHaveBeenCalledWith("teacher", entry.id);
  expect(save).toHaveBeenCalledTimes(1);
  expect(onSaved).toHaveBeenCalledTimes(1);
});
