import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BlockCatalogItem, Pipeline } from "./api";
import { BlockSettings } from "./PipelineSettings";
import type { BlockNode } from "./pipelineGraph";

afterEach(cleanup);

// Настройки агента из blocks/ai_process/generate/block.yaml (задача 28, ADR 0035).
const manifest = {
  id: "ai_process.generate", name: "ИИ-обработка", description: "Готовит результат.", category: "ai_process",
  inputs: [], outputs: [], outcomes: ["ok"], side_effects: false,
  config: {
    type: "object",
    properties: {
      tools: { title: "Какие инструменты разрешить", type: "array", uniqueItems: true,
        items: { type: "string", enum: ["moodle.get_course_grades"] } },
      max_steps: { title: "Сколько раз можно вызвать инструмент", type: "integer", minimum: 1, maximum: 10, default: 5 },
      course_id: { title: "Курс Moodle, который видит агент", type: "integer" },
    },
  },
} as BlockCatalogItem;
const node = { id: "digest", type: "block", block: "ai_process.generate", title: "Сводка", config: {}, inputs: {} } as BlockNode;
const graph = { params: [{ name: "course_id", title: "Курс Moodle", type: "integer" }], nodes: [] } as unknown as Pipeline;

it("teacher turns on the Moodle journal and gives the agent a course parameter", () => {
  const change = vi.fn();
  const { rerender } = render(<BlockSettings graph={graph} node={node} manifest={manifest} change={change} />);
  fireEvent.click(screen.getByLabelText("moodle.get_course_grades"));
  expect(change).toHaveBeenLastCalledWith({ ...node, config: { tools: ["moodle.get_course_grades"] } });

  expect(screen.getByLabelText<HTMLInputElement>("Сколько раз можно вызвать инструмент").placeholder).toBe("5");
  const withTools = { ...node, config: { tools: ["moodle.get_course_grades"] } };
  rerender(<BlockSettings graph={graph} node={withTools} manifest={manifest} change={change} />);
  fireEvent.change(screen.getByLabelText("Курс Moodle, который видит агент · источник"), { target: { value: "course_id" } });
  expect(change).toHaveBeenLastCalledWith({
    ...withTools, config: { tools: ["moodle.get_course_grades"], course_id: { $param: "course_id" } },
  });
});
