// 提交火山外呼结果导出任务
// 用法：在 agent-browser eval 中执行，替换 TASK_ID
// ⚠️ 这是写操作，确认任务已完成（Status=FINISHED）后再执行
const TASK_ID = "1778676465986TH972IWOR7U94NO0Y"; // ← 替换

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

const resp = await fetch(`${API_BASE}/ExportTask`, {
  method: "POST",
  headers: { "X-Csrf-Token": csrfToken, "Content-Type": "application/json" },
  credentials: "include",
  body: JSON.stringify({ TaskId: TASK_ID }),
});
const data = await resp.json();
console.log("Response:", JSON.stringify(data, null, 2));
// 记录返回的 ExportId 供后续轮询使用
const exportId = (data.Result || {}).ExportId || data.ExportId || "未找到 ExportId";
console.log("ExportId:", exportId);
JSON.stringify(data, null, 2);
