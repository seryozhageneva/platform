import { describe, expect, it } from "vitest";
import demo from "../../docs/examples/pipelines/student-lesson-demo.json";
import type { BlockCatalogItem, Pipeline } from "./api";
import { canConnect, connect, graphLinks, newPipeline, readOnlyReason, removeNode } from "./pipelineGraph";

function item(id: string, outputs: BlockCatalogItem["outputs"], inputs: BlockCatalogItem["inputs"], outcomes: string[]): BlockCatalogItem {
  return { id, name: id, description: "", category: "source", inputs, outputs, outcomes, config: {}, side_effects: false };
}

function port(name: string, type: BlockCatalogItem["outputs"][number]["type"]) {
  return { name, title: name, type, list: false, required: true };
}

const blocks = [
  item("source.task_bank", [port("task", "Task")], [port("previous", "Task"), port("verdict", "Verdict")], ["ok", "empty"]),
  item("student.show_task", [port("answer", "Answer")], [port("task", "Task"), port("hint", "Hint")], ["answer", "hint_requested"]),
  item("check.exact", [port("verdict", "Verdict")], [port("task", "Task"), port("answer", "Answer")], ["correct", "wrong"]),
  item("student.tutor", [port("hint", "Hint")], [port("task", "Task"), port("answer", "Answer"), port("verdict", "Verdict"), port("previous_hint", "Hint")], ["hint", "give_up"]),
];
const catalog = new Map(blocks.map((block) => [block.id, block]));
const graph = demo as Pipeline;

describe("Связи в редакторе", () => {
  it("собирает связи учебного графа с пустого полотна и сохраняет параметры и ограничители", () => {
    const empty = {
      ...graph,
      nodes: graph.nodes.map((node) => node.type === "block" ? { ...node, inputs: {} } : node),
      transitions: [],
    };
    const rebuilt = graphLinks(graph).filter((link) => link.remove).reduce<Pipeline>((current, link) => {
      const next = connect(current, catalog, link);
      expect(next, link.id).not.toBeNull();
      return next ?? current;
    }, empty);
    expect(rebuilt).toEqual({ ...graph, transitions: graph.transitions.map((edge) => ({ ...edge, when: edge.when ?? null })) });
    expect(graphLinks(rebuilt).filter((link) => link.id.startsWith("limit:"))).toHaveLength(1);
  });

  it("не добавляет несовместимый порт, дубликат исхода или переход на старт", () => {
    expect(connect(graph, catalog, { source: "show", sourceHandle: "out:answer", target: "tutor", targetHandle: "in:task" })).toBeNull();
    expect(connect(graph, catalog, { source: "show", sourceHandle: "step:answer", target: "tutor", targetHandle: "step" })).toBeNull();
    expect(connect(graph, catalog, { source: "show", sourceHandle: "step:", target: "start", targetHandle: "step" })).toBeNull();
    const record = { type: "Data", of: "summary", list: false } as const;
    expect(canConnect(record, { ...record, of: "essay" })).toBe(false);
    expect(canConnect(record, { ...record, list: true })).toBe(false);
    expect(canConnect(record, { ...record, of: undefined })).toBe(true);
  });

  it("сохраняет несколько источников входа и при удалении узла убирает только его ссылки", () => {
    const second = connect(graph, catalog, { source: "check_exact", sourceHandle: "out:verdict", target: "take_task", targetHandle: "in:verdict" });
    expect(second).toBeNull();
    const alternate = {
      ...graph,
      nodes: [...graph.nodes, { id: "other_check", block: "check.exact", type: "block", title: "", config: {}, inputs: {} } as const],
    };
    const connected = connect(alternate, catalog, { source: "other_check", sourceHandle: "out:verdict", target: "take_task", targetHandle: "in:verdict" });
    expect(connected?.nodes.find((node) => node.id === "take_task")).toMatchObject({
      inputs: { verdict: ["check_exact.verdict", "other_check.verdict"] },
    });
    if (!connected) throw new Error("Вторая привязка не добавлена");
    expect(removeNode(connected, "other_check")).toEqual(graph);
    const removed = removeNode(graph, "take_task");
    expect(removed.nodes.find((node) => node.id === "tutor")).toMatchObject({ limit: { reset_on: null, otherwise: null } });
    expect(graphLinks(removed).some((link) => link.source === "take_task" || link.target === "take_task")).toBe(false);
  });

  it("открывает для просмотра граф с развилкой или недоступным блоком", () => {
    const fresh = newPipeline();
    expect(readOnlyReason(graph, catalog)).toBeUndefined();
    expect(readOnlyReason(graph, new Map())).toContain("отсутствует в каталоге");
    expect(readOnlyReason({
      ...fresh,
      nodes: [...fresh.nodes, { id: "branch", title: "", type: "switch", value: "start.event", field: "trigger" }],
    }, catalog)).toContain("развилку");
  });
});
