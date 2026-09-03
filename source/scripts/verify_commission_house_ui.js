const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");

const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
const duplicates = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
if (duplicates.length) throw new Error("HTML存在重复ID：" + duplicates.join(","));

const required = [
  "commissionRequestPublishCommands", "commissionServicePublishCommands",
  "commissionMyDemandsCommands", "commissionMyServicesCommands",
  "commissionServiceRestockCommands", "commissionServiceRenewCommands",
  "commissionDemandAiSystemPrompt", "commissionServiceAiSystemPrompt",
  "bountyHistory", "commissionServiceTable", "commissionOrderTable",
  "commissionDemandModal", "commissionServiceModal", "commissionPromptHistory",
];
for (const id of required) {
  if (!ids.includes(id)) throw new Error("后台缺少控件：" + id);
  if (!js.includes(id)) throw new Error("脚本未连接控件：" + id);
}

const section = html.slice(html.indexOf('<section id="bounties"'), html.indexOf('<section id="rp"'));
for (const text of ["需求业务规则与独立AI提示词", "服务业务规则与独立AI提示词", "全部需求", "全部服务", "委托订单管理"]) {
  if (!section.includes(text)) throw new Error("委托所页面缺少区域：" + text);
}
if (!section.includes('id="commissionLegacyMarket" class="hidden" hidden')) {
  throw new Error("旧市场后台没有被完全隐藏");
}
if (!js.includes('api("/api/commission-house/overview")')) {
  throw new Error("后台没有连接V2总览接口");
}
if (!js.includes('api("/api/commission-house/demands/"') || !js.includes('api("/api/commission-house/services/"')) {
  throw new Error("需求或服务独立编辑接口缺失");
}

console.log(JSON.stringify({ok: true, html_ids: ids.length, required_controls: required.length}, null, 2));
