export const meta = {
  name: "professional-report",
  description: "Research, verify data, and draft a professional report",
};

const request =
  typeof args === "string" ? args : JSON.stringify(args ?? {}, null, 2);

const [research, dataAnalysis] = await Promise.all([
  agent(
    `Act as the project researcher. Gather traceable evidence for this report request: ${request}. Search project files first, use authoritative current sources only when web tools are available, and clearly label gaps. Return an evidence brief, not a finished report.`,
    { label: "research" },
  ),
  agent(
    `Act as the project data analyst. Determine which claims in this report request require real data: ${request}. If a database is connected, inspect its schema and run only minimal read-only queries. Return metric definitions, verified results, and limitations. If no data is available, identify the missing evidence without inventing values.`,
    { label: "data-analysis" },
  ),
]);

return agent(
  `Act as the professional report writer. Produce a decision-ready report for this request: ${request}.

Research evidence:
${research ?? "Research stage did not return a result."}

Data evidence:
${dataAnalysis ?? "Data-analysis stage did not return a result."}

Separate facts, inference, recommendations, and unknowns. Cite available sources close to claims and do not fill evidence gaps with model memory.`,
  { label: "report-writing" },
);
