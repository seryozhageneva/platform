import type { BlockCatalogItem, Pipeline } from "./api";
import type { components } from "./api.generated";

export type BlockNode = components["schemas"]["BlockNode"];
export type Param = components["schemas"]["Param"];
export type Port = BlockCatalogItem["outputs"][number];
type Node = Pipeline["nodes"][number];
type PortType = Pick<Port, "type" | "of" | "list">;

export const identifier = /^[a-z][a-z0-9_]*$/;

export function newPipeline(): Pipeline {
  const random = Array.from(crypto.getRandomValues(new Uint8Array(12)), (byte) => byte.toString(16).padStart(2, "0"));
  return {
    format: 1, id: `lesson_${random.join("")}`, name: "", description: "", params: [],
    nodes: [{ id: "start", title: "Ученик открыл урок", type: "trigger", launches: [{ type: "student", settings: {} }] }],
    transitions: [],
  };
}

export function makeBlock(graph: Pipeline, item: BlockCatalogItem): BlockNode {
  const prefix = item.id.replaceAll(".", "_");
  let id = prefix;
  for (let index = 2; graph.nodes.some((node) => node.id === id); index++) id = `${prefix}_${index}`;
  return { id, type: "block", title: item.name, block: item.id, config: {}, inputs: {} };
}

export function readOnlyReason(graph: Pipeline, catalog: Map<string, BlockCatalogItem>) {
  for (const node of graph.nodes) {
    if (node.type === "switch" || node.type === "for_each") {
      return "Граф содержит развилку или вложенный цикл. Этот граф доступен для просмотра.";
    }
    if (node.type === "block" && !catalog.has(node.block)) {
      return `Блок «${node.block}» отсутствует в каталоге. Этот граф доступен для просмотра.`;
    }
  }
}

export function updateNode(graph: Pipeline, node: Node): Pipeline {
  return { ...graph, nodes: graph.nodes.map((current) => current.id === node.id ? node : current) };
}

export function sameGraph(left: Pipeline, right: Pipeline) {
  function normalized(graph: Pipeline) {
    return JSON.stringify({
      ...graph,
      params: graph.params.map((param) => ({ ...param, default: param.default ?? null })),
      transitions: graph.transitions.map((edge) => ({ ...edge, when: edge.when ?? null })),
      nodes: graph.nodes.map((node) => {
        if (node.type === "trigger") {
          return { ...node, launches: node.launches.map((launch) => ({ ...launch, cron: launch.cron ?? null })) };
        }
        return {
          ...node,
          limit: node.limit ? { ...node.limit, otherwise: node.limit.otherwise ?? null, reset_on: node.limit.reset_on ?? null } : null,
        };
      }),
    }, (_key, value: unknown) => {
      // PostgreSQL может вернуть ключи объекта JSON в другом порядке.
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
      }
      return value;
    });
  }
  return normalized(left) === normalized(right);
}

export function outputPorts(node: Node, catalog: Map<string, BlockCatalogItem>): Port[] {
  if (node.type === "trigger") return [{ name: "event", title: "Событие", type: "Event", list: false }];
  return node.type === "block" ? catalog.get(node.block)?.outputs ?? [] : [];
}

export function canConnect(source: PortType, target: PortType) {
  const anyData = target.type === "Data" && target.of == null;
  if (anyData && !target.list) return true;
  return source.list === target.list && (anyData || (source.type === target.type && (source.of ?? null) === (target.of ?? null)));
}

export function bindingRefs(value: string | string[] | undefined): string[] {
  return value === undefined ? [] : typeof value === "string" ? [value] : value;
}

export function setBinding(node: BlockNode, input: string, refs: string[]): BlockNode {
  const inputs = { ...node.inputs };
  if (refs.length === 0) delete inputs[input];
  else inputs[input] = refs.length === 1 ? refs.join("") : refs;
  return { ...node, inputs };
}

export function removeNode(graph: Pipeline, id: string): Pipeline {
  return {
    ...graph,
    transitions: graph.transitions.filter((edge) => edge.from !== id && edge.to !== id),
    nodes: graph.nodes.filter((node) => node.id !== id).map((node) => {
      if (node.type !== "block") return node;
      let next = node;
      for (const [input, binding] of Object.entries(node.inputs)) {
        const refs = bindingRefs(binding);
        const remaining = refs.filter((ref) => !ref.startsWith(`${id}.`));
        if (remaining.length !== refs.length) next = setBinding(next, input, remaining);
      }
      if (!node.limit) return next;
      const { otherwise, reset_on } = node.limit;
      if (otherwise !== id && reset_on !== id) return next;
      return {
        ...next,
        limit: { ...node.limit, otherwise: otherwise === id ? null : otherwise, reset_on: reset_on === id ? null : reset_on },
      };
    }),
  };
}

export function paramName(value: unknown): string | undefined {
  if (value && typeof value === "object" && "$param" in value && typeof value.$param === "string") return value.$param;
}

function refersTo(value: unknown, name: string): boolean {
  if (paramName(value) === name) return true;
  return value !== null && typeof value === "object" &&
    Object.values(value).some((nested) => refersTo(nested, name));
}

export function usesParam(graph: Pipeline, name: string) {
  return graph.nodes.some((node) => node.type === "block" &&
    (refersTo(node.config, name) || paramName(node.limit?.max) === name));
}

export function fitsParam(param: Param, type: unknown) {
  return param.type === type || (param.type === "integer" && type === "number");
}

export type Link = {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
  targetHandle: string;
  label?: string;
  remove?: (graph: Pipeline) => Pipeline;
};

export function graphLinks(graph: Pipeline): Link[] {
  const links: Link[] = (graph.transitions ?? []).map((edge) => ({
    id: `step:${edge.from}:${edge.when ?? ""}:${edge.to}`,
    source: edge.from, target: edge.to, sourceHandle: `step:${edge.when ?? ""}`, targetHandle: "step",
    label: edge.when ?? "Дальше",
    remove: (current) => ({
      ...current,
      transitions: current.transitions.filter((item) =>
        item.from !== edge.from || item.to !== edge.to || (item.when ?? null) !== (edge.when ?? null)),
    }),
  }));
  for (const node of graph.nodes) {
    if (node.type === "trigger") continue;
    if (node.limit?.otherwise) links.push({
      id: `limit:${node.id}`, source: node.id, target: node.limit.otherwise,
      sourceHandle: "limit", targetHandle: "step", label: "Предел достигнут",
    });
    if (node.type !== "block") continue;
    for (const [input, binding] of Object.entries(node.inputs ?? {})) {
      for (const ref of bindingRefs(binding)) {
        const [source = "", port = ""] = ref.split(".");
        links.push({
          id: `data:${ref}:${node.id}:${input}`, source, target: node.id,
          sourceHandle: `out:${port}`, targetHandle: `in:${input}`,
          remove: (current) => {
            const target = current.nodes.find((item) => item.id === node.id);
            return target?.type === "block"
              ? updateNode(current, setBinding(target, input, bindingRefs(target.inputs[input]).filter((item) => item !== ref)))
              : current;
          },
        });
      }
    }
  }
  return links;
}

export type Connection = Pick<Link, "source" | "target"> & {
  sourceHandle?: string | null; targetHandle?: string | null;
};

export function connect(graph: Pipeline, catalog: Map<string, BlockCatalogItem>, connection: Connection): Pipeline | null {
  const { source, target, sourceHandle, targetHandle } = connection;
  const from = graph.nodes.find((node) => node.id === source);
  const to = graph.nodes.find((node) => node.id === target);
  if (!from || to?.type !== "block" || !sourceHandle || !targetHandle) return null;

  if (sourceHandle.startsWith("step:") && targetHandle === "step") {
    const when = sourceHandle.slice("step:".length) || null;
    if (when && (from.type !== "block" || !catalog.get(from.block)?.outcomes.includes(when))) return null;
    if (graph.transitions.some((edge) => edge.from === source && (edge.when ?? null) === when)) return null;
    return { ...graph, transitions: [...graph.transitions, { from: source, to: target, when }] };
  }
  if (!sourceHandle.startsWith("out:") || !targetHandle.startsWith("in:")) return null;
  const output = outputPorts(from, catalog).find((port) => port.name === sourceHandle.slice("out:".length));
  const input = catalog.get(to.block)?.inputs.find((port) => port.name === targetHandle.slice("in:".length));
  if (!output || !input || output.same_as || output.from_config || !canConnect(output, input)) return null;
  const refs = bindingRefs(to.inputs[input.name]);
  const ref = `${source}.${output.name}`;
  return refs.includes(ref) ? null : updateNode(graph, setBinding(to, input.name, [...refs, ref]));
}
