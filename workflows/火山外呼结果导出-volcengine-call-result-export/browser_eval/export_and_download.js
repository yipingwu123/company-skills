// 火山外呼结果一键导出 + 轮询下载链接
// ⚠️ 写操作，仅在任务状态为 FINISHED 后执行
// 用法：agent-browser eval --session <session> --script export_and_download.js

const TASK_ID = "1778676465986TH972IWOR7U94NO0Y"; // ← 替换

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

async function apiGet(path) {
  const r = await fetch(API_BASE + path, {
    method: "GET",
    headers: { "X-Csrf-Token": csrfToken },
    credentials: "include",
  });
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "X-Csrf-Token": csrfToken, "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  return r.json();
}

// 1. 先确认任务状态
const taskResp = await apiGet(`/QueryTask?TaskId=${encodeURIComponent(TASK_ID)}`);
const taskResult = taskResp.Result || {};
console.log("任务状态:", taskResult.Status, "总数:", taskResult.TotalCount, "接通:", taskResult.AnswerCount);

if (taskResult.Status !== "FINISHED") {
  throw new Error(`任务尚未完成，当前状态：${taskResult.Status}，请等待后再执行。`);
}

// 2. 提交导出
const exportResp = await apiPost("/ExportTask", { TaskId: TASK_ID });
console.log("提交导出响应:", JSON.stringify(exportResp));
const exportId = (exportResp.Result || {}).ExportId || exportResp.ExportId;
if (!exportId) {
  throw new Error("未获取到 ExportId，响应：" + JSON.stringify(exportResp));
}
console.log("ExportId:", exportId);

// 3. 轮询导出状态（最多等 5 分钟）
let downloadUrl = null;
for (let i = 0; i < 60; i++) {
  await new Promise(r => setTimeout(r, 5000));
  const statusResp = await apiGet(`/QueryExportStatus?ExportId=${encodeURIComponent(exportId)}`);
  const sr = statusResp.Result || statusResp;
  console.log(`轮询 #${i+1}: Status=${sr.Status}, DownloadUrl=${sr.DownloadUrl || "无"}`);
  if (sr.Status === "SUCCESS" && sr.DownloadUrl) {
    downloadUrl = sr.DownloadUrl;
    break;
  }
  if (sr.Status === "FAILED") {
    throw new Error("导出失败: " + JSON.stringify(sr));
  }
}

if (!downloadUrl) throw new Error("轮询超时（5分钟），导出未完成。");

// 4. 返回摘要（供 agent 记录）
JSON.stringify({
  task_id: TASK_ID,
  task_status: taskResult.Status,
  total_count: taskResult.TotalCount,
  answer_count: taskResult.AnswerCount,
  connected_count: taskResult.ConnectedCount,
  export_id: exportId,
  download_url: downloadUrl,
}, null, 2);
