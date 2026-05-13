// 查询火山外呼任务状态
// 用法：在 agent-browser eval 中执行，替换 TASK_ID
const TASK_ID = "1778676465986TH972IWOR7U94NO0Y"; // ← 替换为实际 task_id

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

const resp = await fetch(`${API_BASE}/QueryTask?TaskId=${encodeURIComponent(TASK_ID)}`, {
  method: "GET",
  headers: { "X-Csrf-Token": csrfToken },
  credentials: "include",
});
const data = await resp.json();
const result = data.Result || {};
console.log("Status:", result.Status);
console.log("TotalCount:", result.TotalCount);
console.log("AnswerCount:", result.AnswerCount);
console.log("ConnectedCount:", result.ConnectedCount);
JSON.stringify({ Status: result.Status, TotalCount: result.TotalCount, AnswerCount: result.AnswerCount, ConnectedCount: result.ConnectedCount }, null, 2);
