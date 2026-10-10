/* 逐鹿 · 栅格地形数据生成器 —— 前端逻辑
   一个文件，无框架。四件事：读 /api/会话 建界面 → 参数改了就比契约值 → 跑的时候接 SSE
   日志流点亮阶段 → 数据组一键下载。 */
"use strict";
const $ = s => document.querySelector(s);
let 元信息 = null, 跑着 = false, 事件流 = null, 下行 = 0;

/* 参数项的元数据：键 → [中文名, 单位/说明, 类型]。
   契约值从 /api/会话 的 契约门槛 来，别在这儿抄第二份。 */
const 管线项 = [
  ["cell", "格边长（度）", "0.0526 ≈ 5.86 km；0.0625 ≈ 6.9 km", "num"],
  ["river_min", "河网流量门槛", "m³/s；河网密度只有这一个旋钮", "num"],
];
const 门槛项 = [
  ["山地起伏", "山地起伏", "m，起伏大于它算山地（adr/0013）", "num"],
  ["丘陵起伏", "丘陵起伏", "m", "num"],
  ["高原海拔", "高原海拔", "m，高而平算高原", "num"],
  ["高原起伏上限", "高原起伏上限", "m", "num"],
  ["沙占比", "沙占比", "%，GSDP30 有沙占比（adr/0012）", "num"],
  ["盐盘占比", "盐盘占比", "%，GLWD-3 盐盘占比（adr/0014）", "num"],
  ["水体占比", "水体占比", "%", "num"],
  ["湖岸收口上限格", "湖岸收口上限", "格，大于它当海", "num"],
  ["盐田距海格", "盐田距海", "格", "num"],
  ["海冰频率", "海冰频率", "0–1，1.0 = 常年", "num"],
  ["海冰最低纬度", "海冰最低纬度", "°N", "num"],
];
const 开关项 = [
  ["no_veg", "不读土地覆盖（只剩海陆两档，快）"],
  ["no_terrain", "只出地块层（不读高程）"],
];
const 门槛开关 = [
  ["干湖床接回沙砾", "干湖床接回 沙/砾 裸地（咸海那一片）"],
  ["干湖床接回草甸草原", "干湖床接回 草甸/草原"],
];
const 组名 = {core:"底图与汉地", basins:"流域底", modern:"现代边界", foreign:"外国县一级",
  climate:"柯本气候", rivers:"河网 HydroRIVERS", soil:"沙丘形态 GSDP30", ice:"海冰 NSIDC",
  lake:"湖沼库 GLWD", volcano:"全新世火山"};

/* ---------------- 建界面 ---------------- */
function 建参数(){
  const p = 元信息.参数, c = 元信息.契约门槛;
  const box = $("#pipe-params"); box.innerHTML = "";
  for (const [k, 名, 说] of 管线项){
    box.insertAdjacentHTML("beforeend",
      `<div class="f" data-k="${k}"><label>${名}</label>
       <input type="text" value="${p[k]}" data-type="num">
       <div class="c">${说}</div></div>`);
  }
  for (const [k, 名] of 开关项){
    box.insertAdjacentHTML("beforeend",
      `<div class="f tog"><input type="checkbox" id="p-${k}" ${p[k] ? "checked" : ""}>
       <label for="p-${k}">${名}</label></div>`);
  }
  const rbox = $("#rule-params"); rbox.innerHTML = "";
  for (const [k, 名, 说] of 门槛项){
    rbox.insertAdjacentHTML("beforeend",
      `<div class="f" data-k="${k}" data-contract="${c[k]}"><label>${名}</label>
       <input type="text" value="${p.门槛[k]}" data-type="num">
       <div class="c">契约 ${c[k]} · ${说}</div></div>`);
  }
  for (const [k, 名] of 门槛开关){
    rbox.insertAdjacentHTML("beforeend",
      `<div class="f tog"><input type="checkbox" id="r-${k}" ${p.门槛[k] ? "checked" : ""}>
       <label for="r-${k}">${名}</label></div>`);
  }
  document.querySelectorAll(".f input").forEach(el =>
    el.addEventListener("input", 查门槛));
  查门槛();
}

function 查门槛(){
  let 变 = [];
  document.querySelectorAll("#rule-params .f[data-k]").forEach(el => {
    const 同 = Number(el.querySelector("input").value) === Number(el.dataset.contract);
    el.classList.toggle("changed", !同);
    if (!同) 变.push(el.dataset.k);
  });
  const b = $("#badge-contract");
  b.className = "chip " + (变.length ? "warn" : "ok");
  b.textContent = 变.length ? `门槛改了 ${变.length} 项` : "契约值";
  b.title = 变.length ? "与规格 §8 的契约值不同：" + 变.join("、") + " —— 这一趟的产物不算契约产品" :
    "规则门槛全部等于规格 §8 写死的契约值";
  return 变;
}

function 读参数(){
  const r = {门槛:{}};
  document.querySelectorAll("#pipe-params .f[data-k]").forEach(el =>
    r[el.dataset.k] = Number(el.querySelector("input").value));
  document.querySelectorAll("#rule-params .f[data-k]").forEach(el =>
    r.门槛[el.dataset.k] = Number(el.querySelector("input").value));
  for (const [k] of 开关项) r[k] = $("#p-" + k).checked;
  for (const [k] of 门槛开关) r.门槛[k] = $("#r-" + k).checked;
  return r;
}

function 建阶段(){
  const ol = $("#stage-list"); ol.innerHTML = "";
  元信息.阶段.forEach((s, i) => {
    ol.insertAdjacentHTML("beforeend",
      `<li id="st-${i + 1}"><span class="dot"></span>
       <div><div class="nm">${i + 1}. ${s.名}</div><div class="ds">${s.说明}</div></div>
       <div class="tm">·</div></li>`);
  });
}

function 建数据组(){
  const box = $("#groups"); box.innerHTML = "";
  for (const g of 元信息.数据组){
    const 全 = g.缺 === 0 && g.残 === 0;
    const 类 = 全 ? "ready" : (g.有 ? "part" : "missing");
    const 比 = Math.round(g.有 / g.项 * 100);
    box.insertAdjacentHTML("beforeend",
      `<div class="g ${类}" id="g-${g.组}">
         <div class="gh"><span class="gn">${组名[g.组] || g.组}</span>
           <button class="ghost sm" data-g="${g.组}">下载</button></div>
         <div class="gm">${g.组} · ${g.项} 项 · ${(g.字节/1048576).toFixed(0)} MB</div>
         <div class="gbar"><i style="width:${比}%"></i></div>
         <div class="st ${全 ? "ok" : (g.有 ? "warn" : "bad")}">
           已就绪 ${g.有}/${g.项}${g.残 ? " · 残 " + g.残 : ""}${g.缺 ? " · 缺 " + g.缺 : ""}</div>
       </div>`);
  }
  box.querySelectorAll("button[data-g]").forEach(b =>
    b.onclick = () => 取数(b.dataset.g, b));
  $("#data-note").textContent =
    "下载走 fetch_map_data.py（幂等、可续传、按字节数校验）；原始件都落在 地图/地图数据/原始数据/（不进 git）。";
}

/* ---------------- 日志 ---------------- */
function 写行(s, cls){
  const d = document.createElement("span");
  d.className = "l " + (cls || "");
  d.textContent = s;
  $("#log").appendChild(d);
  if ($("#follow").checked) $("#log").scrollTop = $("#log").scrollHeight;
}
function 认行(s){
  let cls = "";
  if (/^\[\d+\/\d+\]/.test(s)) cls = "step";
  else if (/完成（/.test(s)) cls = "ok";
  else if (/^\s*(⚠️|! )/.test(s) || /⚠️/.test(s)) cls = "warn";
  else if (/Traceback|Error|错误|断言|破坏/.test(s)) cls = "err";
  else if (/^\s{2}/.test(s)) cls = "dim";
  写行(s, cls);
  // 阶段：`[3/6] 气候与派生 —— …` / `完成（0.9 s）` / `跳过`
  const m = s.match(/^\[(\d+)\/(\d+)\]\s*(.*)$/);
  if (m){
    const i = +m[1], rest = m[3];
    const li = $("#st-" + i);
    if (li){
      if (/^（--只跑到/.test(rest) || /跳过/.test(rest)){
        li.className = "skip"; li.querySelector(".tm").textContent = "跳过";
      } else if (/完成（/.test(rest)){
        li.className = "done";
        li.querySelector(".tm").textContent = (rest.match(/（([\d.]+ s)）/) || [, ""])[1];
      } else {
        document.querySelectorAll("#stage-list li.run").forEach(x => x.className = "");
        li.className = "run"; li.querySelector(".tm").textContent = "跑…";
      }
    }
  }
}
function 接流(){
  if (事件流) 事件流.close();
  下行 = 0;
  事件流 = new EventSource("/api/流?from=0");
  事件流.onmessage = e => { try{ 认行(JSON.parse(e.data)); 下行++; }catch(_){} };
  事件流.addEventListener("状态", e => {
    const s = JSON.parse(e.data);
    跑着 = s.运行中;
    $("#badge-run").className = "chip " + (跑着 ? "busy" : "mute");
    $("#badge-run").textContent = 跑着 ? `跑着 · ${s.标题}（${s.已跑秒|0}s）` : "空闲";
    $("#btn-run").disabled = 跑着; $("#btn-stop").disabled = !跑着;
    if (!跑着 && s.返回码 !== null && s.返回码 !== undefined){
      $("#stage-timer").textContent = s.返回码 === 0 ? "上一趟：全部完成 ✓" : `上一趟：返回码 ${s.返回码}（看日志）`;
      if (s.返回码 === 0){ 提示("跑完了，产物已刷新", "ok"); 刷产物(); 刷数据组(); }
      else 提示(`退出码 ${s.返回码} —— 日志里有原因`, "bad");
    }
  });
  事件流.addEventListener("完", () => { try{事件流.close();}catch(_){} });
  事件流.onerror = () => { /* 服务关了或还没起活：EventSource 自己会重连 */ };
}

/* ---------------- 动作 ---------------- */
async function 起(q, 体, 按钮){
  if (按钮) 按钮.disabled = true;
  try{
    const r = await fetch(q, {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(体 || {})});
    const j = await r.json();
    if (!r.ok){ 提示(j.错 || ("HTTP " + r.status), "bad"); return false; }
    return true;
  }catch(e){ 提示("连不上本地服务：" + e.message, "bad"); return false; }
  finally{ if (按钮) 按钮.disabled = false; }
}

async function 跑(){
  const 变 = 查门槛();
  if (变.length && !confirm(`规则门槛有 ${变.length} 项不是契约值（${变.join("、")}）。\n` +
      `这一趟的产物将不算契约产品（规格 §8 的数是契约）。仍然继续？`)) return;
  $("#log").innerHTML = ""; 
  document.querySelectorAll("#stage-list li").forEach(li => { li.className = ""; li.querySelector(".tm").textContent = "·"; });
  if (await 起("/api/跑", {参数: 读参数()}, $("#btn-run"))) { 接流(); 提示("开始生成（读缓存的话约两分钟）"); }
}
async function 取数(组, 按钮){
  if (跑着) return 提示("已经有一件活在跑，先等它结束或中断", "bad");
  if (await 起("/api/取数", {组}, 按钮)){ 接流(); 提示(`开始下载：${组名[组] || 组}`); }
}
async function 刷数据组(){
  const r = await fetch("/api/会话"); 元信息 = await r.json(); 建数据组();
}
async function 刷产物(){
  const r = await fetch("/api/产物"); const j = await r.json();
  $("#products tbody").innerHTML = j.产物.map(p =>
    `<tr><td>${p.名}</td><td class="mono">${p.目录}</td>
     <td class="num">${(p.字节/1048576).toFixed(2)} MB</td>
     <td class="mono">${p.时间}</td><td class="mono">${p.md5}</td></tr>`).join("");
}
function 提示(s, 类){
  const t = $("#toast"); t.textContent = s; t.className = "toast show " + (类 || "");
  clearTimeout(提示.t); 提示.t = setTimeout(() => t.className = "toast " + (类 || ""), 4200);
}

/* ---------------- 起 ---------------- */
(async function(){
  const r = await fetch("/api/会话");
  元信息 = await r.json();
  建参数(); 建阶段(); 建数据组(); 刷产物();
  $("#btn-run").onclick = 跑;
  $("#btn-stop").onclick = () => 起("/api/停", {}, null).then(() => 提示("已请求中断"));
  $("#btn-clear").onclick = () => $("#log").innerHTML = "";
  $("#btn-open").onclick = () => 起("/api/打开目录", {}, null);
  $("#btn-refresh").onclick = 刷产物;
  $("#btn-all").onclick = async () => { if (await 起("/api/取数", {组:"all"}, $("#btn-all"))) { 接流(); 提示("开始下载全部数据组（约 600 MB）"); } };
  $("#btn-selfcheck").onclick = async () => { if (await 起("/api/自检", {}, $("#btn-selfcheck"))) { 接流(); 提示("跑 check_terrain（契约 + 地理常识断言）"); } };
  $("#btn-default").onclick = () => {
    const c = 元信息.契约门槛;
    document.querySelectorAll("#rule-params .f[data-k]").forEach(el =>
      el.querySelector("input").value = c[el.dataset.k]);
    document.querySelectorAll("#rule-params .f.tog input, #pipe-params .f.tog input")
      .forEach(el => el.checked = true);
    查门槛(); 提示("门槛已恢复契约默认（管线参数没动）", "ok");
  };
  接流();
})();
