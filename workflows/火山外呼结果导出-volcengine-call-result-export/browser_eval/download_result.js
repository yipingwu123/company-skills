// 轮询导出状态并获取下载链接
// 先运行 export_task.js，得到 ExportId 后再运行此文件
const EXPORT_ID = "REPLACE_WITH_EXPORT_ID"; // ← 替换

const API_BASE = "/console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01";
const csrfToken = decodeURIComponent(
  document.cookie.split(";").find(c => c.trim().startsWith("csrfToken="))?.split("=")[1] || ""
);

async function pollStatus(maxAttempts = 20, intervalMs = 3000) {
  for (let i = 0; i < maxAttempts; i++) {
    const resp = await fetch(`${API_BASE}/QueryExportStatus?ExportId=${encodeURIComponent(EXPORT_ID)}`, {
      method: "GET",
      headers: { "X-Csrf-Token": csrfToken },
      credentials: "include",
    });
    const data = await resp.json();
    const result = data.Result || data;
    console.log(`轮询 #${i+1}: Status=${result.Status}, DownloadUrl=${result.DownloadUrl || "无"}`);
    if (result.Status === "SUCCESS" && result.DownloadUrl) {
      return result.DownloadUrl;
    }
    if (result.Status === "FAILED") throw new Error("导出失败: " + JSON.stringify(result));
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error("轮询超时");
}

const downloadUrl = await pollStatus();
console.log("下载链接:", downloadUrl);
downloadUrl;
