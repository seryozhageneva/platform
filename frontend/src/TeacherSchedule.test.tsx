import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { TeacherSchedule } from "./TeacherSchedule";

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  api: { schedule: vi.fn(), saveSchedule: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("сохраняет параметры, показывает ошибку и даёт выключить расписание", async () => {
  const schedule = { enabled: false, cron: "0 18 * * 5", params: {} };
  vi.mocked(api.schedule).mockResolvedValue(schedule);
  vi.mocked(api.saveSchedule)
    .mockRejectedValueOnce(new ApiError(422, "ошибка", [{ code: "bad_param", message: "Укажи период" }]))
    .mockResolvedValueOnce({ ...schedule, enabled: true, params: { days: 7 } })
    .mockResolvedValueOnce({ ...schedule, params: { days: 7 } });

  render(<TeacherSchedule accountId="teacher" pipelineId="pipeline" version={2} disabled={false}
    params={[{ name: "days", title: "Дни", type: "integer" }]} onSessionChange={vi.fn()} />);

  const enabled = await screen.findByRole("checkbox", { name: "Включено" });
  const save = screen.getByRole("button", { name: "Сохранить расписание" });
  fireEvent.click(enabled);
  fireEvent.click(save);
  expect((await screen.findByRole("alert")).textContent).toBe("Укажи период");

  fireEvent.change(screen.getByRole("spinbutton", { name: "Дни" }), { target: { value: "7" } });
  fireEvent.click(save);
  await screen.findByText("Настройки расписания сохранены.");
  expect(api.saveSchedule).toHaveBeenLastCalledWith("teacher", "pipeline", {
    enabled: true, expected_version: 2, params: { days: 7 },
  });

  fireEvent.click(enabled);
  fireEvent.click(save);
  await screen.findByText("Настройки расписания сохранены.");
  expect(api.saveSchedule).toHaveBeenLastCalledWith("teacher", "pipeline", {
    enabled: false, expected_version: 2, params: { days: 7 },
  });
});

it("отличает сброс текстового параметра от явной пустой строки", async () => {
  const schedule = { enabled: true, cron: "0 18 * * 5" };
  vi.mocked(api.schedule).mockResolvedValue({ ...schedule, params: { topic: "Дроби" } });
  vi.mocked(api.saveSchedule)
    .mockResolvedValueOnce({ ...schedule, params: {} })
    .mockResolvedValueOnce({ ...schedule, params: { topic: "" } });
  render(<TeacherSchedule accountId="teacher" pipelineId="pipeline" version={2} disabled={false}
    params={[{ name: "topic", title: "Тема", type: "string", default: "Алгебра" }]} onSessionChange={vi.fn()} />);

  await screen.findByDisplayValue("Дроби");
  fireEvent.click(screen.getByRole("button", { name: "Тема · сбросить значение" }));
  expect(screen.getByPlaceholderText("Алгебра")).toBeTruthy();
  const save = screen.getByRole("button", { name: "Сохранить расписание" });
  fireEvent.click(save);
  await screen.findByText("Настройки расписания сохранены.");
  expect(api.saveSchedule).toHaveBeenLastCalledWith("teacher", "pipeline", {
    enabled: true, expected_version: 2, params: {},
  });

  fireEvent.click(screen.getByRole("button", { name: "Тема · задать пустую строку" }));
  expect(screen.queryByPlaceholderText("Алгебра")).toBeNull();
  fireEvent.click(save);
  await screen.findByText("Настройки расписания сохранены.");
  expect(api.saveSchedule).toHaveBeenLastCalledWith("teacher", "pipeline", {
    enabled: true, expected_version: 2, params: { topic: "" },
  });
});
