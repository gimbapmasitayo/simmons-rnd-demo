# -*- coding: utf-8 -*-
"""사내 시험 성적서 자동 작성 - 사내망 전용 웹앱 (Flask).

성적서 종류를 고르면 그에 맞는 화면과 계산이 붙는다.
  라돈 · 토론 완제품  → core.py
  라돈 원자재         → material.py
"""
import os, io, re, sys, tempfile, shutil, json

# 명령창 글자표(윈도우는 cp949)로 못 찍는 글자가 하나라도 있으면 파이썬이
# 그 자리에서 죽는다. 실제로 «—» 하나 때문에 서버가 다시 켜지지 않았다.
# 못 찍는 글자는 물음표로 바꾸고 계속 가게 한다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass
from datetime import date, datetime
from urllib.parse import quote
from flask import Flask, request, render_template_string, send_file, jsonify, send_from_directory, abort
import core, material, kc, ks, stats, portal, news, trend, products, report, events, standards, verify, precheck, certs
import time

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024      # 사진 여러 장 대비

PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>사내 시험 성적서 자동 작성 | SIMMONS R&D</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" as="style" crossorigin
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>
.wmodal{position:fixed;inset:0;background:rgba(10,10,11,.55);z-index:90;display:flex;align-items:center;justify-content:center;padding:20px}
.wbox{background:#fff;max-width:640px;width:100%;padding:26px 28px 22px;border:1px solid #e3e0d9;max-height:90vh;overflow:auto}
.wbox .eyebrow{font-size:10.5px;letter-spacing:.18em;color:#84848a;font-weight:600}
.wbox h3{font-size:18px;margin:4px 0 6px;letter-spacing:-.01em}
.wbox .wh p{font-size:13px;color:#3a3a40;line-height:1.6;margin:0 0 14px}
.wbox ul{list-style:none;margin:0;padding:0;border-top:1px solid #e3e0d9}
.wbox li{padding:11px 0;border-bottom:1px solid #eeebe4;font-size:13px;line-height:1.55}
.wbox li b{display:block;color:#8c3325}
.wbox li .why{display:block;color:#3a3a40}
.wbox li .how{display:block;color:#84848a;font-size:12px}
.wack{display:flex;gap:8px;align-items:flex-start;font-size:13px;margin:16px 0 14px;cursor:pointer}
.wbtn{display:flex;justify-content:flex-end;gap:8px}
.wbtn button{font:inherit;font-size:13px;padding:9px 16px;border:none;background:#0a0a0b;color:#fff;cursor:pointer}
.wbtn button[disabled]{background:#b4b4b9;cursor:default}
.wbtn button.ghost{background:#fff;color:#0f0f11;border:1px solid #e3e0d9}
.dupmsg{font-size:11.5px;color:#8c3325;margin-top:4px}.dupmsg.ok{color:#23573f}
/* ═══════════════════════════════════════════════════════════════
   시몬스 사내 시험 성적서 자동 작성 — 화면 디자인

   무채색 하나로 간다. 금색·남색 같은 '고급스러워 보이려는' 색을 빼고,
   먹빛과 종이빛, 그리고 머리카락 굵기의 선만 쓴다. 시몬스 브랜드가
   그렇게 생겼고, 종이 성적서와 나란히 놓아도 어색하지 않다.
   글씨는 Pretendard 한 벌로 통일하고 굵기와 자간으로만 층을 만든다.
   ═══════════════════════════════════════════════════════════════ */
:root{
  /* 바탕은 팬톤 2026 «Cloud Dancer»(11-4201). 흰색이 올해의 색으로 뽑힌 해라
     장식을 걷어내고 흰 여백과 큰 글씨로만 승부한다. */
  --ink:#0f0f11; --ink-2:#3a3a40; --mute:#84848a; --faint:#b4b4b9;
  --line:#e3e0d9; --line-2:#eeebe4; --paper:#fff; --bg:#f1efea; --black:#0a0a0b;
  --ok:#23573f; --ok-bg:#eef3f0; --warn:#7a5d15; --warn-bg:#faf5e6;
  --err:#8c3325; --err-bg:#fbefed;
  --sh:0 1px 1px rgba(16,16,18,.02), 0 8px 26px -18px rgba(16,16,18,.30);
  --ease:cubic-bezier(.22,.68,.32,1);
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{
  font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,
              'Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif;
  font-weight:400; font-size:14px; line-height:1.7; color:var(--ink);
  background:var(--bg); -webkit-font-smoothing:antialiased;
  font-feature-settings:'tnum' 0; word-break:keep-all;
}
[hidden]{display:none !important}
.wrap{max-width:1060px;margin:0 auto;padding:0 32px 160px}
body.step1 .wrap{padding-bottom:96px}

/* ─────────────── 맨 위 띠 + 표지 (한 덩어리의 검정) ───────────────
   밝은 종이빛만으로는 «만들다 만 것» 처럼 보인다. 위쪽에 먹빛 덩어리를
   두어 브랜드북 표지처럼 첫인상을 만들고, 그 아래를 일하는 자리로 둔다. */
{{ nav_css }}
.topbar.float{border-bottom:1px solid rgba(255,255,255,.14)}
.prac{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--mute);cursor:pointer;margin-right:18px;white-space:nowrap}
.prac input{accent-color:var(--black)}
.ver{font-size:10.5px;font-weight:500;letter-spacing:.08em;color:rgba(255,255,255,.42);
  font-variant-numeric:tabular-nums;text-align:right}

.masthead{background:var(--black);color:#fff;position:relative;overflow:hidden}
.masthead::after{content:"";position:absolute;left:0;right:0;bottom:0;height:1px;
  background:linear-gradient(90deg,rgba(255,255,255,.22),rgba(255,255,255,0) 62%)}
.hero{max-width:1060px;margin:0 auto;padding:84px 32px 88px;position:relative}
@keyframes up{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
/* 한 덩어리로 나타나지 않고 위에서부터 차례로 올라온다.
   요즘 큰 글씨 디자인이 정지된 그림처럼 굳어 보이지 않게 하는 방법이다. */
.hero h1,.hero p,.hero .meta{animation:up .72s var(--ease) both}
.hero p{animation-delay:.1s}
.hero .meta{animation-delay:.19s}
.hero h1{font-size:clamp(38px,6.6vw,76px);font-weight:150;letter-spacing:-.055em;
  line-height:1.04;color:#fff}
.hero h1 b{font-weight:700;letter-spacing:-.06em}
.hero p{margin-top:30px;font-size:15px;font-weight:300;color:rgba(255,255,255,.58);
  max-width:520px;line-height:1.9}
.hero .meta{display:flex;flex-wrap:wrap;gap:0 60px;margin-top:54px;
  padding-top:26px;border-top:1px solid rgba(255,255,255,.13)}
.hero .meta div{font-size:9.5px;font-weight:600;letter-spacing:.19em;
  color:rgba(255,255,255,.38)}
.hero .meta b{display:block;margin-top:7px;font-size:12.5px;font-weight:400;
  letter-spacing:0;color:rgba(255,255,255,.88);font-variant-numeric:tabular-nums}

/* 2단계는 일하는 화면이다. 표지를 매번 지나쳐 스크롤하지 않도록 접는다. */
body:not(.step1) .hero{padding:30px 32px 32px}
body:not(.step1) .hero h1{font-size:21px;font-weight:300;letter-spacing:-.03em;
  line-height:1.4}
body:not(.step1) .hero h1 br{display:none}
body:not(.step1) .hero h1 b{font-weight:600}
body:not(.step1) .hero h1 b::before{content:" "}
body:not(.step1) .hero p,
body:not(.step1) .hero .meta{display:none}

/* ─────────────── 단계 표시 ─────────────── */
.steps{display:flex;align-items:center;gap:16px;margin:52px 0 24px}
.steps span{display:flex;align-items:center;gap:9px;font-size:11px;font-weight:600;
  letter-spacing:.15em;color:var(--faint);transition:color .3s var(--ease)}
.steps span.on{color:var(--black)}
.steps span i{font-style:normal;font-variant-numeric:tabular-nums;font-weight:700}
.steps .bar-line{flex:1;height:1px;background:var(--line);max-width:120px}

/* ─────────────── 구역 제목 ─────────────── */
.sec{display:flex;align-items:baseline;gap:16px;margin:56px 0 20px}
.sec .no{font-size:11px;font-weight:700;letter-spacing:.14em;color:var(--faint);
  font-variant-numeric:tabular-nums;line-height:1}
.sec h2{font-size:18px;font-weight:600;letter-spacing:-.02em;color:var(--black);
  white-space:nowrap}
.sec .rule{flex:1;height:1px;background:var(--line)}
.sec .hint{font-size:11.5px;font-weight:350;color:var(--mute);text-align:right}

.card{background:var(--paper);border:1px solid var(--line);padding:38px 40px;
  box-shadow:var(--sh)}

/* ─────────────── 1단계 · 성적서 고르기 ─────────────── */
.kinds{display:grid;grid-template-columns:1fr 1fr;gap:1px;
  background:var(--line);border:1px solid var(--line);box-shadow:var(--sh);
  animation:up .72s var(--ease) both;animation-delay:.26s}
.kind{background:var(--paper);padding:52px 42px 44px;cursor:pointer;min-height:262px;
  display:flex;flex-direction:column;
  transition:background .34s var(--ease),color .34s var(--ease)}
.kind .k-n{font-size:10.5px;font-weight:700;letter-spacing:.2em;color:var(--faint);
  transition:color .34s var(--ease)}
.kind .k-t{margin-top:18px;font-size:clamp(28px,3.2vw,36px);font-weight:250;
  letter-spacing:-.045em;color:var(--black);line-height:1.2;
  transition:color .34s var(--ease)}
.kind .k-go{margin-top:auto;padding-top:36px;display:flex;align-items:center;gap:12px;
  font-size:10.5px;font-weight:600;letter-spacing:.2em;color:var(--mute);
  transition:color .34s var(--ease)}
.kind .k-go i{display:block;width:26px;height:1px;background:currentColor;
  transition:width .34s var(--ease)}
.kind:hover{background:var(--black)}
.kind:hover .k-t,.kind:hover .k-go,.kind:hover .k-n{color:#fff}
.kind:hover .k-n{color:rgba(255,255,255,.42)}
.kind:hover .k-go i{width:52px}

/* ─────────────── 2단계 맨 위 ─────────────── */
.chosen{display:flex;align-items:center;gap:16px;margin:44px 0 0;flex-wrap:wrap}
.back{background:none;border:none;font:inherit;font-size:12.5px;font-weight:450;
  color:var(--mute);cursor:pointer;padding:6px 0;transition:color .2s}
.back:hover{color:var(--black)}
.chip{font-size:12px;font-weight:600;letter-spacing:.02em;color:#fff;
  background:var(--black);padding:7px 15px}

/* ─────────────── 입력 ─────────────── */
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:26px 30px}
.field label{display:block;font-size:10px;font-weight:600;letter-spacing:.16em;
  color:var(--faint);margin-bottom:9px}
.field input{width:100%;height:42px;border:none;border-bottom:1px solid var(--line);
  background:transparent;padding:0 1px;font:inherit;font-size:14.5px;
  color:var(--ink);transition:border-color .2s}
.field input:hover{border-bottom-color:var(--faint)}
.field input:focus{outline:none;border-bottom-color:var(--black)}
.field input::placeholder{color:#cfcdc8;font-weight:350}

/* ─────────────── 측정 카드 ─────────────── */
.run{background:var(--paper);border:1px solid var(--line);margin-bottom:20px;
  box-shadow:var(--sh);overflow:hidden;animation:up .38s var(--ease)}
.run-head{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:22px 34px;border-bottom:1px solid var(--line-2)}
.run-title{display:flex;align-items:center;gap:15px}
.run-title .dot{width:30px;height:30px;flex:none;background:var(--black);color:#fff;
  display:flex;align-items:center;justify-content:center;font-size:12px;
  font-weight:600;font-variant-numeric:tabular-nums}
.run-title .t{font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--black)}
.run-title .c{font-size:11.5px;font-weight:350;color:var(--mute);margin-top:1px}
.rm{background:none;border:1px solid transparent;font:inherit;font-size:11.5px;
  color:var(--mute);cursor:pointer;padding:6px 12px;transition:.18s}
.rm:hover{color:var(--err);border-color:#ecd8d4;background:var(--err-bg)}
.run-body{padding:28px 34px 30px}

.uploads{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  background:var(--line);border:1px solid var(--line)}
.drop{position:relative;background:var(--paper);padding:22px 14px 20px;
  text-align:center;cursor:pointer;transition:background .2s;min-height:118px;
  display:flex;flex-direction:column;align-items:center;justify-content:center}
.drop:hover{background:#fbfaf8}
.drop.over{background:#f2f0eb}
.drop.filled{background:#fbfbf9}
.drop .ico{font-size:15px;color:var(--faint);line-height:1;margin-bottom:10px;
  transition:color .2s}
.drop.filled .ico{color:var(--black)}
.drop .lab{font-size:12.5px;font-weight:600;color:var(--ink);letter-spacing:-.01em}
.drop .tag{font-size:9.5px;font-weight:600;letter-spacing:.14em;color:var(--faint);margin-top:4px}
.drop .fn{font-size:10px;font-weight:450;color:var(--ink-2);margin-top:8px;
  max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drop input{position:absolute;inset:0;opacity:0;cursor:pointer}
.drop .thumb{width:100%;height:54px;object-fit:cover;margin-bottom:8px;display:none}
.drop.has-thumb .thumb{display:block}
.drop.has-thumb .ico{display:none}
.drop .bad{position:absolute;left:0;right:0;bottom:5px;font-size:9.5px;color:var(--err);
  text-align:center;display:none}
.drop.mismatch{background:var(--err-bg)}
.drop.mismatch .bad{display:block}
.drop.mismatch .ico{color:var(--err)}
.drop .edit{position:absolute;right:7px;top:7px;z-index:3;display:none;cursor:pointer;
  border:1px solid var(--line);background:rgba(255,255,255,.95);color:var(--ink);
  font:inherit;font-size:10px;font-weight:600;letter-spacing:.06em;padding:4px 9px;
  transition:.18s}
.drop.has-thumb .edit{display:block}
.drop .edit:hover{background:var(--black);border-color:var(--black);color:#fff}
.drop .cut{display:none;font-size:9.5px;font-weight:600;letter-spacing:.1em;
  color:var(--mute);margin-top:5px}
.drop.cropped .cut{display:block}

.kc-bulk{display:block;text-align:center;border:1px dashed var(--line);margin-bottom:6px;padding:26px 14px}
.kc-bulk .tag{letter-spacing:0;font-weight:450;font-size:11px;margin-top:6px}
.kc-swap-hint{font-size:11px;font-weight:350;color:var(--mute);padding:6px 0 10px;text-align:center}
#kcPhotos .kc-ph .drop.has-thumb{cursor:pointer}
#kcPhotos .kc-ph .drop.next{outline:2px dashed var(--black);outline-offset:-2px}
#kcPhotos .kc-ph .drop.next .lab::after{content:" ← 다음 자리";font-size:10px;color:var(--mute);font-weight:500}
#kcPhotos .kc-ph .drop .rmv{position:absolute;left:7px;top:7px;z-index:3;display:none;width:20px;height:20px;
  line-height:18px;text-align:center;font-size:13px;background:var(--paper);border:1px solid var(--line);
  color:var(--ink-2);cursor:pointer;border-radius:50%}
#kcPhotos .kc-ph .drop.has-thumb .rmv{display:block}
#kcPhotos .kc-ph .drop .rmv:hover{background:var(--err);border-color:var(--err);color:#fff}
.kc-tray{margin:6px 0 4px;padding:12px 14px;border:1px solid var(--line-2);background:#fbfbf9}
.kc-tray-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;
  font-size:11px;color:var(--mute);margin-bottom:10px}
.kc-tray-head b{color:var(--black);font-weight:600}
.kc-tray-btns{display:flex;gap:6px}
.kc-tray-btns button{font:inherit;font-size:11px;font-weight:500;cursor:pointer;padding:6px 10px;
  border:1px solid var(--line);background:var(--paper);color:var(--ink-2)}
.kc-tray-btns button:hover{border-color:var(--black);color:var(--black)}
.kc-tray-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(88px,1fr));gap:8px}
.kc-tray-grid .tt{position:relative;aspect-ratio:1.1;overflow:hidden;cursor:pointer;background:#ddd;
  border:2px solid transparent;transition:.15s}
.kc-tray-grid .tt img{width:100%;height:100%;object-fit:cover;display:block}
.kc-tray-grid .tt:hover{border-color:var(--black)}
.kc-tray-grid .tt.pick{border-color:var(--black);box-shadow:0 0 0 2px var(--paper) inset}
.kc-tray-grid .tt .n{position:absolute;left:4px;bottom:4px;font-size:9px;background:rgba(11,11,12,.7);color:#fff;
  padding:1px 5px;max-width:calc(100% - 8px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#kcPhotos .drop.pick{outline:2px solid var(--black);outline-offset:-2px}
.jbox{margin-top:22px;border-top:1px solid var(--line)}
.jbox summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:14px;padding:14px 0;font-size:12.5px}
.jbox summary::-webkit-details-marker{display:none}
.jbox summary::before{content:"▸";font-size:11px;color:var(--mute);transition:transform .15s}
.jbox[open] summary::before{transform:rotate(90deg)}
.jsum{font-weight:600}
.jsum.bad{color:var(--err)}
.jhint{font-size:11px;color:var(--mute);font-weight:350}
.jbox[open] .jhint{display:none}
.jlist{border-top:1px solid var(--line-2)}
.jgrp{font-size:10px;font-weight:600;letter-spacing:.16em;color:var(--mute);padding:16px 0 4px}
.jrow{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:7px 0;
      border-bottom:1px solid var(--line-2);font-size:12.5px;cursor:pointer}
.jrow span{flex:1}
.jrow select{width:96px;flex:none;padding:6px 0;font:inherit;font-size:12px;border:none;
      border-bottom:1px solid var(--line);background:transparent}
.jrow:has(option[value="부적합"]:checked) span,.jrow.bad span{color:var(--err);font-weight:600}
.kc-ph{padding:18px 0}
.kc-ph[hidden]{display:none}
.kc-ph:not([hidden])+.kc-ph:not([hidden]){border-top:1px solid var(--line-2)}
.kc-ph-t{display:flex;align-items:center;gap:12px;font-size:13px;font-weight:600;
  color:var(--black);letter-spacing:-.01em;margin-bottom:14px}
.kc-ph-t .dot{width:24px;height:24px;flex:none;background:var(--black);color:#fff;
  font-size:11px;display:flex;align-items:center;justify-content:center}
.field select{font:inherit;width:100%;padding:10px 0;border:none;border-bottom:1px solid var(--line);
  background:transparent;color:var(--ink)}
.smp{margin-top:30px;padding-top:26px;border-top:1px solid var(--line-2)}
.smp-head{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:16px}
.smp-head .t{font-size:10px;font-weight:600;letter-spacing:.16em;color:var(--faint)}
.smp-head .n{font-size:11.5px;font-weight:500;color:var(--ink-2);
  font-variant-numeric:tabular-nums}
.smp-row{display:grid;grid-template-columns:26px 1fr 130px 38px;gap:10px;
  align-items:center;margin-bottom:9px}
.smp-row .i{font-size:11.5px;font-weight:600;color:var(--faint);text-align:center;
  font-variant-numeric:tabular-nums}
.smp-row input{height:41px;border:1px solid var(--line);background:var(--paper);
  padding:0 13px;font:inherit;font-size:14px;color:var(--ink);width:100%;transition:.18s}
.smp-row input:focus{outline:none;border-color:var(--black)}
.smp-row input::placeholder{color:#cfcdc8;font-weight:350}
.smp-row .x{height:41px;background:none;border:1px solid var(--line);color:var(--faint);
  cursor:pointer;font-size:15px;line-height:1;transition:.18s}
.smp-row .x:hover{border-color:#ecd8d4;color:var(--err);background:var(--err-bg)}
.addlink{background:none;border:none;font:inherit;font-size:12.5px;font-weight:600;
  color:var(--ink-2);cursor:pointer;padding:9px 0;transition:color .18s}
.addlink:hover{color:var(--black)}
.add-run{width:100%;border:1px dashed var(--line);background:transparent;
  padding:20px;font:inherit;font-size:12.5px;font-weight:500;letter-spacing:.04em;
  color:var(--mute);cursor:pointer;transition:.22s}
.add-run:hover{border-color:var(--black);border-style:solid;color:var(--black);
  background:var(--paper)}
.add-run:disabled{opacity:.4;cursor:not-allowed}

/* ─────────────── 아래 실행 바 ─────────────── */
.bar{position:fixed;left:0;right:0;bottom:0;z-index:40;background:rgba(255,255,255,.9);
  -webkit-backdrop-filter:saturate(1.6) blur(16px);
  backdrop-filter:saturate(1.6) blur(16px);border-top:1px solid var(--line)}
.bar-in{max-width:1060px;margin:0 auto;padding:16px 32px;display:flex;
  align-items:center;justify-content:space-between;gap:24px}
.tally{display:flex;gap:34px;align-items:baseline;flex-wrap:wrap}
.tally div{font-size:10px;font-weight:600;letter-spacing:.15em;color:var(--faint)}
.tally b{font-size:20px;font-weight:300;color:var(--black);margin-right:6px;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.gen{background:var(--black);color:#fff;border:1px solid var(--black);
  padding:15px 44px;font:inherit;font-size:13px;font-weight:600;letter-spacing:.12em;
  cursor:pointer;transition:.24s;white-space:nowrap;flex:none}
.gen:hover:not(:disabled){background:#fff;color:var(--black)}
.gen:disabled{opacity:.4;cursor:progress}
.msg{max-width:1060px;margin:0 auto;padding:0 32px}
.msg .in{display:none;padding:13px 17px;font-size:12.5px;margin-bottom:12px;
  line-height:1.6;border:1px solid transparent}
.msg.show .in{display:block}
.msg.err .in{background:var(--err-bg);color:var(--err);border-color:#eedcd8}
.msg.ok .in{background:var(--ok-bg);color:var(--ok);border-color:#d7e5dd}
.msg.warn .in{background:var(--warn-bg);color:var(--warn);border-color:#ebdfbe}

/* ─────────────── 사진 편집기 ─────────────── */
.solo{display:grid;grid-template-columns:290px 1fr;gap:1px;background:var(--line);
  border:1px solid var(--line)}
.solo .drop{min-height:180px}
.out{background:var(--paper);padding:22px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:14px}
.out-empty{font-size:12px;font-weight:350;color:var(--mute);text-align:center;line-height:1.9}
.out-img{display:none;max-width:100%;max-height:270px;border:1px solid var(--line)}
.out-meta{display:none;font-size:10.5px;font-weight:500;letter-spacing:.06em;
  color:var(--mute);font-variant-numeric:tabular-nums}
.out-acts{display:none;gap:10px}
.out.done .out-empty{display:none}
.out.done .out-img,.out.done .out-meta{display:block}
.out.done .out-acts{display:flex}
.out-acts button,.out-send button{font:inherit;font-size:12px;font-weight:500;
  cursor:pointer;padding:10px 17px;border:1px solid var(--line);
  background:var(--paper);color:var(--ink-2);transition:.18s}
.out-acts button:hover,.out-send button:hover{border-color:var(--black);color:var(--black)}
.out-acts .ok{background:var(--black);border-color:var(--black);color:#fff;
  font-weight:600;letter-spacing:.1em;padding:11px 24px}
.out-acts .ok:hover{background:var(--paper);color:var(--black)}
.out-send{display:none;align-items:center;gap:9px;flex-wrap:wrap;justify-content:center;
  width:100%;padding-top:16px;border-top:1px solid var(--line-2)}
.out.done .out-send{display:flex}
.out-send select{height:39px;border:1px solid var(--line);background:var(--paper);
  padding:0 11px;font:inherit;font-size:12.5px;color:var(--ink);cursor:pointer}
.out-send select:focus{outline:none;border-color:var(--black)}
.run.flash{animation:flash 1.4s var(--ease)}
@keyframes flash{0%{box-shadow:0 0 0 2px var(--black)}100%{box-shadow:var(--sh)}}

/* ─────────────── 사진 다듬기 창 ─────────────── */
.mask{position:fixed;inset:0;z-index:80;background:rgba(11,11,12,.72);
  display:none;align-items:center;justify-content:center;padding:24px}
.mask.on{display:flex}
.ed{background:var(--paper);width:100%;max-width:960px;overflow:hidden;
  box-shadow:0 40px 100px -30px rgba(0,0,0,.7);animation:up .3s var(--ease)}
.ed-head{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:22px 28px;border-bottom:1px solid var(--line-2)}
.ed-head .t{font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--black)}
.ed-head .s{font-size:11.5px;font-weight:350;color:var(--mute);margin-top:3px}
.ed-x{background:none;border:none;font:inherit;font-size:22px;line-height:1;
  color:var(--faint);cursor:pointer;padding:0 4px;transition:color .18s}
.ed-x:hover{color:var(--err)}
.stage{background:#131316;padding:18px;display:flex;align-items:center;
  justify-content:center;min-height:220px;touch-action:none;
  -webkit-user-select:none;user-select:none}
.cbox{position:relative;line-height:0;overflow:hidden}
.cbox canvas{display:block}
.cropbox{position:absolute;border:1px solid rgba(255,255,255,.96);cursor:move;
  box-shadow:0 0 0 100vmax rgba(11,11,12,.66)}
.cropbox .h{position:absolute;width:13px;height:13px;box-sizing:border-box;
  border:2px solid #fff;background:rgba(11,11,12,.35)}
.cropbox .nw{left:0;top:0;cursor:nwse-resize}
.cropbox .ne{right:0;top:0;cursor:nesw-resize}
.cropbox .sw{left:0;bottom:0;cursor:nesw-resize}
.cropbox .se{right:0;bottom:0;cursor:nwse-resize}
.ed-foot{display:flex;align-items:center;justify-content:space-between;gap:18px;
  flex-wrap:wrap;padding:18px 28px;border-top:1px solid var(--line-2)}
.ed-foot .tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ed-foot button{font:inherit;font-size:12px;font-weight:500;cursor:pointer;
  padding:10px 15px;border:1px solid var(--line);background:var(--paper);
  color:var(--ink-2);transition:.18s}
.ed-foot .tools button:hover{border-color:var(--black);color:var(--black)}
.ed-foot .acts{display:flex;gap:10px}
.ed-foot .ok{background:var(--black);border-color:var(--black);color:#fff;
  font-weight:600;letter-spacing:.1em;padding:11px 26px}
.ed-foot .ok:hover{background:var(--paper);color:var(--black)}
.ed-note{font-size:11px;font-weight:350;color:var(--mute);padding:0 28px 18px;
  line-height:1.8}
.ed-note b{font-weight:600;color:var(--ink-2);font-variant-numeric:tabular-nums}
/* ── 표시하기(마킹) ── */
.ed-tabs{display:flex;padding:0 28px;border-bottom:1px solid var(--line-2);gap:2px}
.ed-tabs button{font:inherit;font-size:12px;font-weight:500;cursor:pointer;
  padding:12px 18px;border:none;background:none;color:var(--mute);
  border-bottom:2px solid transparent;margin-bottom:-1px;transition:.18s}
.ed-tabs button:hover{color:var(--ink-2)}
.ed-tabs button.on{color:var(--black);font-weight:600;border-bottom-color:var(--black)}
.cbox #mk{position:absolute;left:0;top:0}
.mask.mark-mode #cropbox{display:none}
.mask.mark-mode .cbox{cursor:crosshair}
.mask.mark-mode .ed-foot .tools{display:none}
.mask.mark-mode .ratios{display:none}
.markbar{display:none;align-items:center;gap:14px;flex-wrap:wrap}
.mask.mark-mode .markbar{display:flex}
.mgrp{display:flex;align-items:center;gap:6px}
.mgrp+.mgrp{padding-left:12px;border-left:1px solid var(--line)}
.mgrp>span{font-size:9.5px;font-weight:600;letter-spacing:.15em;color:var(--faint);
  margin-right:2px}
.markbar button{font:inherit;font-size:12px;font-weight:500;cursor:pointer;
  padding:9px 13px;border:1px solid var(--line);background:var(--paper);
  color:var(--ink-2);transition:.18s}
.markbar button:hover{border-color:var(--black);color:var(--black)}
.markbar button.on{background:var(--black);border-color:var(--black);color:#fff}
.markbar button:disabled{opacity:.35;cursor:default}
.markbar button:disabled:hover{border-color:var(--line);color:var(--ink-2)}
.sw{width:22px;height:22px;padding:0;border-radius:50%;border:2px solid var(--line-2);
  cursor:pointer;transition:.18s}
.sw:hover{transform:scale(1.12)}
.sw.on{border-color:var(--black);box-shadow:0 0 0 2px var(--paper) inset}
.ratios{display:none;align-items:center;gap:6px;flex-wrap:wrap;
  margin-left:8px;padding-left:12px;border-left:1px solid var(--line)}
.mask.solo-mode .ratios{display:flex}
.ratios span{font-size:9.5px;font-weight:600;letter-spacing:.15em;color:var(--faint);
  margin-right:3px}
.ratios button{padding:9px 12px !important;font-size:11.5px !important}
.ratios button.on{border-color:var(--black) !important;background:var(--black) !important;
  color:#fff !important}

/* ─────────────── 좁은 화면 ─────────────── */
@media (max-width:900px){
  .wrap{padding-left:22px;padding-right:22px}
  .bar-top,.bar-in,.msg{padding-left:22px;padding-right:22px}
  .grid{grid-template-columns:repeat(2,1fr)}
  .uploads{grid-template-columns:repeat(2,1fr) !important}
  .kinds{grid-template-columns:1fr}
  .kind{padding:40px 28px 34px}
  .solo{grid-template-columns:1fr}
  .card{padding:28px 24px}
  .run-head,.run-body{padding-left:22px;padding-right:22px}
  .bar-in{flex-direction:column;align-items:stretch}
  .gen{width:100%}
  .ed-foot{flex-direction:column;align-items:stretch}
  .ed-foot .acts button{flex:1}
  .ratios{margin-left:0;padding-left:0;border-left:none}
}
@media (max-width:520px){
  .hero{padding-top:56px}
  .grid{grid-template-columns:1fr}
  .smp-row{grid-template-columns:22px 1fr 38px}
  .smp-row .sz{grid-column:2/3}
  .hero .meta{gap:0 30px}
}
</style>
</head>
<body class="step1">

{{ nav|safe }}

<div class="masthead">
  <header class="hero">
    <h1>시험 성적서<br><b>자동 작성</b></h1>
    <p>측정 원본과 시료 사진을 올리면 성적서가 완성되어 내려받아집니다.
       표는 시료 수에 맞춰 늘어나고 줄어들며, 빈 칸을 남기지 않습니다.</p>
    <div class="meta">
      <div>시험 대상<b>완제품 · 원자재 · 매트리스</b></div>
      <div>망 구분<b>사내망 전용 · 외부 전송 없음</b></div>
    </div>
  </header>
</div>

<div class="wrap">
  <div class="steps">
    <span id="stepA" class="on"><i>01</i> 성적서 종류</span>
    <span class="bar-line"></span>
    <span id="stepB"><i>02</i> 성적서 작성</span>
  </div>

  <!-- ── 1단계: 성적서 종류만 고른다 ── -->
  <section id="step1">
    <div class="kinds" id="kinds">
      <div class="kind" data-kind="finished">
        <div class="k-n">라돈 · 토론</div>
        <div class="k-t">완제품</div>
        <div class="k-go"><i></i>고르기</div>
      </div>
      <div class="kind" data-kind="material">
        <div class="k-n">라돈</div>
        <div class="k-t">원자재</div>
        <div class="k-go"><i></i>고르기</div>
      </div>
      <div class="kind" data-kind="kc">
        <div class="k-n">KC 안전기준</div>
        <div class="k-t">매트리스</div>
        <div class="k-go"><i></i>고르기</div>
      </div>
      <div class="kind" data-kind="ks">
        <div class="k-n">KS 규격</div>
        <div class="k-t">매트리스</div>
        <div class="k-go"><i></i>고르기</div>
      </div>
    </div>
  </section>

  <!-- ── 2단계: 고른 성적서를 쓴다 ── -->
  <section id="step2" hidden>
  <div class="chosen">
    <button type="button" class="back" id="back">‹&nbsp; 성적서 종류 다시 고르기</button>
    <span class="chip" id="chosenName"></span>
  </div>

  <form id="form" autocomplete="off">
    <div class="sec"><span class="no">01</span><h2>성적서 정보</h2><span class="rule"></span></div>
    <div class="card">
      <div class="grid">
        <div class="field"><label>성적서번호 <a href="#" id="autoNo" style="font-weight:400;font-size:11px;margin-left:6px">자동 채번</a></label><input name="report_no" placeholder="L-26-059" autocomplete="off"><div class="dupmsg" id="dupMsg" hidden></div>
          <div id="reissueBox" hidden style="margin-top:6px"><label style="font-size:11px;color:var(--mute)">재발행 사유</label><select name="reissue_reason" style="font:inherit;font-size:12.5px;padding:6px 8px;border:1px solid var(--line);background:#fff;width:100%"><option>입력 오류</option><option>측정 재시험</option><option>양식 변경</option><option>기타</option></select></div></div>
        <div class="field"><label>시료명 (대표)</label><input name="sample_title" placeholder="특판 5종"></div>
        <div class="field"><label>용도</label><input name="purpose" value="품질 테스트"></div>
        <div class="field"><label>의뢰일자</label><input name="request_date" placeholder="2026년 03월 06일"></div>
        <div class="field"><label>발급일자</label><input name="issue_date" value="{{today}}"></div>
        <div class="field"><label>발행자 <span style="font-weight:400;font-size:11px;color:var(--mute)">(이 PC에 기억)</span></label><input name="issuer" placeholder="이름" autocomplete="off"></div>
        <div class="field"><label>시험장소</label><input name="place" value="라돈 측정실"></div>
        <div class="field"><label>시험환경 · 온도</label><input name="temp" value="상온"></div>
        <div class="field"><label>시험환경 · 습도</label><input name="humid" value="-"></div>
        <div class="field"><label>시험방법</label><input name="method" value="라돈 및 토론 시험표준 (S-QI-L01)"></div>
        <div class="field kc-only" hidden><label>시험일자</label><input name="test_date" placeholder="2026년 08월 04일 ~ 08월 05일"></div>
      </div>
    </div>

    <!-- ── KC 내구시험에만 있는 입력 ── -->
    <div id="kcBox" hidden>
      <div class="sec"><span class="no">01-b</span><h2>KC 검사 항목</h2><span class="rule"></span>
        <span class="hint">내구성·수직하중은 CSV 로 자동 계산합니다. 나머지는 육안·공인기관 결과를 적으세요</span></div>
      <div class="card">
        <div class="grid">
          <div class="field"><label>내구성 · 수직하중 횟수</label>
            <select name="last_cycle">{% for c in kc_last_choices %}<option value="{{c}}">{{ "{:,}".format(c) }}회</option>{% endfor %}</select></div>
          <div class="field"><label>치수 · 나비 (mm)</label><input name="dim_w" placeholder="1805" inputmode="numeric"></div>
          <div class="field"><label>치수 · 길이 (mm)</label><input name="dim_l" placeholder="2093" inputmode="numeric"></div>
          <div class="field"><label>치수 · 두께 (mm)</label><input name="dim_t" placeholder="291" inputmode="numeric"></div>
          <div class="field"><label>겉감 품질 · 공인기관 성적서</label><input name="fabric" placeholder="Katri 성적서 SPHA26-FU000233K"></div>
        </div>
        <div class="grid" style="margin-top:14px">
          <div class="field"><label>겉모양 판정</label><select name="judge_appearance"><option>적합</option><option>부적합</option></select></div>
          <div class="field"><label>치수 판정</label><select name="judge_dims"><option>적합</option><option>부적합</option></select></div>
          <div class="field"><label>재료 판정</label><select name="judge_material"><option>적합</option><option>부적합</option></select></div>
          <div class="field"><label>내구성 육안 판정</label><select name="judge_durability"><option>적합</option><option>부적합</option></select></div>
          <div class="field"><label>겉감 품질 판정</label><select name="judge_fabric"><option>적합</option><option>부적합</option></select></div>
        </div>
      </div>

    </div>

    <!-- ── KS 매트리스에만 있는 입력 ── -->
    <div id="ksBox" hidden>
      <div class="sec"><span class="no">01-b</span><h2>KS 검사 항목</h2><span class="rule"></span>
        <span class="hint">내구성·수직하중은 CSV 로, 치수는 허용차로 자동 판정합니다. 나머지는 육안·공인기관 결과를 적으세요</span></div>
      <div class="card">
        <div class="grid">
          <div class="field"><label>치수 · 나비 (mm)</label><input name="ks_dim_w" placeholder="1485" inputmode="numeric"></div>
          <div class="field"><label>치수 · 길이 (mm)</label><input name="ks_dim_l" placeholder="1982" inputmode="numeric"></div>
          <div class="field"><label>치수 · 두께 (mm)</label><input name="ks_dim_t" placeholder="405" inputmode="numeric"></div>
          <div class="field"><label>기준 치수 · 나비 (+30, −20)</label><input name="ks_spec_w" placeholder="1500" inputmode="numeric"></div>
          <div class="field"><label>기준 치수 · 길이 (+30, −20)</label><input name="ks_spec_l" placeholder="2000" inputmode="numeric"></div>
          <div class="field"><label>기준 치수 · 두께 (±20)</label><input name="ks_spec_t" placeholder="340" inputmode="numeric"></div>
          <div class="field"><label>겉감 품질 · 공인기관 성적서</label><input name="ks_fabric" placeholder="Katri 성적서 SPHA25-FU000704K, SPHA25-FU000702K"></div>
          <div class="field"><label>치수 판정</label><select name="ks_dims_judge"><option>자동</option><option>적합</option><option>부적합</option></select></div>
        </div>
        <details class="jbox" id="ksJudge">
          <summary><span class="jsum" id="ksJudgeSum">육안 검사 18항목 · 전부 적합</span>
            <span class="jhint">부적합이 있으면 열어서 그 항목만 고르세요</span></summary>
        <div class="jlist">
          {% for key, grp, name, short in ks_judges %}
          {% if loop.first or ks_judges[loop.index0 - 1][1] != grp %}<div class="jgrp">{{ ks_groups[grp] }}</div>{% endif %}
          <label class="jrow" data-short="{{ short }}"><span>{{ name }}</span>
            <select name="ks_judge_{{key}}"><option>적합</option><option>부적합</option></select></label>
          {% endfor %}
        </div>
        </details>
      </div>
    </div>

    <div class="sec"><span class="no">02</span><h2>측정</h2><span class="rule"></span>
      <span class="hint" id="runHint">챔버에 한꺼번에 넣어 1회 잰 것이 «측정» 한 건입니다</span></div>
    <div id="runs"></div>
    <button type="button" class="add-run" id="addRun">＋&nbsp; 측정 회차 추가</button>

    <!-- ── KC 검사 사진 (CSV 아래에 온다) ── -->
    <div id="kcPhotos" hidden>
      <div class="sec"><span class="no">02-b</span><h2>검사 사진</h2><span class="rule"></span>
        <span class="hint">줄마다 최대 3장. 전부 놓고 누르는 순서대로 앉히거나, 칸에 직접 넣습니다. 비워 두면 빈칸</span></div>
      <div class="card">
        <label class="drop kc-bulk" id="kcBulk" data-key="kbulk">
          <div class="ico">◇</div>
          <div class="lab">사진 전부 여기에 놓기</div>
          <div class="tag">아래 대기 칸에 늘어놓습니다. 그다음 사진을 누르면 «다음 자리» 에 차례로 들어갑니다</div>
          <div class="fn"></div>
          <input type="file" accept="image/*" multiple>
        </label>
        <div class="kc-tray" id="kcTray" hidden>
          <div class="kc-tray-head">
            <span>대기 중 <b id="kcTrayN">0</b>장 — 누르는 순서대로 들어갑니다. 특정 자리에 넣으려면 사진을 누른 뒤 그 자리를 누르세요</span>
            <span class="kc-tray-btns">
              <button type="button" id="kcByTime" title="EXIF 촬영 시각 순서로 남은 자리를 채웁니다">찍은 시각 순으로 채우기</button>
              <button type="button" id="kcTrayClear">대기 칸 비우기</button>
            </span>
          </div>
          <div class="kc-tray-grid" id="kcTrayGrid"></div>
        </div>
        <div class="kc-swap-hint">들어간 사진은 두 장을 차례로 누르면 자리가 바뀝니다. 사진 위 ×는 빼기입니다.</div>
        {% for kind, pref, rows in (("kc", "kphoto", kc_photo_rows), ("ks", "sphoto", ks_photo_rows)) %}
        {% for row, name in rows %}
        <div class="kc-ph" data-kind="{{kind}}">
          <div class="kc-ph-t"><span class="dot">{{ loop.index }}</span>{{ name }}</div>
          <div class="uploads" style="grid-template-columns:repeat(3,1fr)">
            {% for k in range(3) %}
            <label class="drop" id="drop_{{pref}}_{{row}}_{{k}}" data-key="{{pref}}_{{row}}_{{k}}" data-pho="1">
              <img class="thumb" alt="">
              <div class="ico">◇</div>
              <div class="lab">사진 {{ k + 1 }}</div>
              <div class="tag">JPG · PNG</div>
              <div class="fn"></div>
              <button type="button" class="edit">다듬기</button><div class="cut">직접 자른 사진</div>
              <span class="rmv" title="빼서 대기 칸으로">×</span>
              <div class="bad"></div>
              <input type="file" name="{{pref}}_{{row}}_{{k}}" accept="image/*" multiple>
            </label>
            {% endfor %}
          </div>
        </div>
        {% endfor %}
        {% endfor %}
      </div>
    </div>
  </form>

  <div class="sec"><span class="no">03</span><h2>사진 편집기</h2><span class="rule"></span>
    <span class="hint">성적서와 상관없이, 사진만 잘라 내려받고 싶을 때</span></div>
  <div class="card">
    <div class="solo">
      <label class="drop" data-key="solo">
        <div class="ico">◇</div>
        <div class="lab">사진 고르기</div>
        <div class="tag">JPG · PNG · 끌어다 놓기</div>
        <div class="fn"></div>
        <input type="file" accept="image/*">
      </label>
      <div class="out" id="soloOut">
        <div class="out-empty">사진을 올리면 편집기가 열립니다.<br>
          비율은 «성적서 칸 · 4:3 · 1:1 · 자유» 중에서 고르세요.</div>
        <img class="out-img" alt="">
        <div class="out-meta"></div>
        <div class="out-acts">
          <button type="button" id="soloEdit">다시 다듬기</button>
          <button type="button" class="ok" id="soloSave">내려받기</button>
        </div>
        <div class="out-send">
          <select id="soloRun"></select>
          <button type="button" id="soloPut">이 사진을 시료 사진으로 넣기</button>
        </div>
      </div>
    </div>
  </div>
  </section>
</div>

<div class="bar" id="bar" hidden>
  <div class="msg" id="msg"><div class="in" id="msgin"></div></div>
  <div class="bar-in">
    <div class="tally">
      <div><b id="tRuns">1</b>회 측정</div>
      <div><b id="tSmp">0</b>종 시료</div>
      <div><b id="tPho">0</b>장 사진</div>
    </div>
    <label class="prac" title="연습으로 만드는 성적서. 실적에서 빠지고, 성적서번호 칸에 «연습용» 이 찍힙니다"><input type="checkbox" id="practice">연습용</label>
    <label class="prac" title="과거에 손으로 만든 성적서를 프로그램으로 다시 만들어 실적에 넣습니다. 발급일자를 과거 날짜로 적으면 그 날짜 기준으로 집계되고 기록에 «소급» 이 남습니다"><input type="checkbox" id="backdated">소급 등록</label>
    <button type="submit" form="form" class="gen" id="gen">성 적 서 &nbsp;생 성</button>
  </div>
</div>

<div class="mask" id="mask">
  <div class="ed">
    <div class="ed-head">
      <div>
        <div class="t">사진 다듬기</div>
        <div class="s">성적서 사진칸에 들어갈 자리를 고르세요. 틀은 사진칸과 같은 모양입니다.</div>
      </div>
      <button type="button" class="ed-x" id="edX" title="닫기">&times;</button>
    </div>
    <div class="ed-tabs">
      <button type="button" id="tabCrop" class="on">자르기</button>
      <button type="button" id="tabMark">표시하기</button>
    </div>
    <div class="stage">
      <div class="cbox" id="cbox">
        <canvas id="cv"></canvas>
        <canvas id="mk"></canvas>
        <div class="cropbox" id="cropbox">
          <i class="h nw" data-g="nw"></i><i class="h ne" data-g="ne"></i>
          <i class="h sw" data-g="sw"></i><i class="h se" data-g="se"></i>
        </div>
      </div>
    </div>
    <div class="ed-foot">
      <div class="tools">
        <button type="button" data-rot="-1">↺&nbsp; 왼쪽으로 돌리기</button>
        <button type="button" data-rot="1">↻&nbsp; 오른쪽으로 돌리기</button>
        <button type="button" id="edReset">처음 자리로</button>
        <div class="ratios" id="ratios"><span>비율</span>
          <button type="button" data-a="box" class="on">성적서 칸</button>
          <button type="button" data-a="1.3333">4 : 3</button>
          <button type="button" data-a="1">1 : 1</button>
          <button type="button" data-a="0">자유</button>
        </div>
      </div>
      <div class="markbar" id="markbar">
        <div class="mgrp">
          <button type="button" class="mt on" data-t="arrow">↗ 화살표</button>
          <button type="button" class="mt" data-t="rect">□ 사각형</button>
          <button type="button" class="mt" data-t="ellipse">○ 원</button>
          <button type="button" class="mt" data-t="pen">✎ 자유선</button>
          <button type="button" class="mt" data-t="text">T 글자</button>
        </div>
        <div class="mgrp" id="swatches"><span>색</span></div>
        <div class="mgrp"><span>굵기</span>
          <button type="button" class="mw" data-w="thin">얇게</button>
          <button type="button" class="mw on" data-w="mid">보통</button>
          <button type="button" class="mw" data-w="bold">굵게</button>
        </div>
        <div class="mgrp">
          <button type="button" id="mDel" disabled>삭제</button>
          <button type="button" id="mUndo" disabled>↶ 되돌리기</button>
          <button type="button" id="mRedo" disabled>↷ 다시</button>
          <button type="button" id="mClear">전체 지우기</button>
        </div>
      </div>
      <div class="acts">
        <button type="button" id="edCancel">취소</button>
        <button type="button" class="ok" id="edOk">이 자리로 자르기</button>
      </div>
    </div>
    <div class="ed-note" id="edNote">틀 안을 끌면 자리가 옮겨지고, 네 귀퉁이를 끌면 크기가 바뀝니다.
      손대지 않으면 프로그램이 고른 자리가 그대로 쓰입니다. &nbsp;·&nbsp;
      고른 자리 <b id="edSize">-</b> 화소 &nbsp;·&nbsp; 표시 <b id="markCount">0</b> 개</div>
  </div>
</div>

<script>
const MAX_SMP=40, MAX_TOTAL={{max_samples}};

/* 성적서 종류마다 다른 것 — 올리는 파일, 시료 칸, 사진칸 비율, 회차 상한.
   나머지(끌어다 놓기 · 장비 알아맞히기 · 사진 편집기 · 디자인)는 함께 쓴다. */
const KINDS={
  finished:{
    name:'완제품 (라돈 · 토론)', aspect:{{photo_aspect}}, maxRuns:{{max_runs}}, size:true,
    hint:'챔버에 한꺼번에 넣어 1회 잰 것이 «측정» 한 건입니다',
    slots:[['rad7','RAD7','라돈·토론 측정'],
           ['rd200','RD200','라돈 측정'],
           ['frd','FRD400','배경농도'],
           ['photo','시료 사진','JPG · PNG']],
    expect:{rad7:['RAD7'],rd200:['RD200','RadonEye Plus'],frd:['FRD400']},
    nice:{rad7:'RAD7',rd200:'RD200',frd:'FRD400 배경'}},
  material:{
    name:'원자재 (라돈)', aspect:{{photo_aspect_m}}, maxRuns:{{max_runs_m}}, size:false,
    hint:'챔버 하나가 «측정» 한 건입니다. 같은 회차의 두 챔버는 배경농도 파일을 똑같이 올리세요',
    slots:[['frd','FRD400','배경농도'],
           ['eye','RadonEye Plus','측정'],
           ['photo','시료 사진','JPG · PNG']],
    expect:{frd:['FRD400'],eye:['RadonEye Plus','RD200']},
    nice:{frd:'FRD400 배경',eye:'RadonEye Plus'}},
  kc:{
    name:'매트리스 (KC 안전기준)', aspect:{{photo_aspect_k}}, maxRuns:1, size:false, kc:true,
    hint:'내구시험기 프로그램이 저장한 CSV 한 개로 성적서 한 장을 만듭니다',
    slots:[['csv','내구시험 CSV','Mattress Endurance Tester']],
    expect:{csv:['KC']},
    nice:{csv:'내구시험 CSV'},
    defaults:{purpose:'매트리스 품질관리용',place:'내구성 테스트실',temp:'상  온',
              method:'안전기준준수대상 생활용품 부속서 19 (침대 매트리스), 침대/매트리스 내구성시험기 시험방법(S-QI-L05)'}},
  ks:{
    name:'매트리스 (KS 규격)', aspect:{{photo_aspect_s}}, maxRuns:1, size:false, kc:true, ks:true,
    hint:'내구시험기 프로그램이 저장한 CSV 한 개로 3쪽 성적서를 만듭니다 (다섯 스텝 전부)',
    slots:[['csv','내구시험 CSV','Mattress Endurance Tester']],
    expect:{csv:['KC']},
    nice:{csv:'내구시험 CSV'},
    defaults:{purpose:'매트리스 품질관리용',place:'내구성 테스트실',temp:'상  온',
              method:'가정용 일반침대(KS G 4300:2020), 침대/매트리스 내구성시험기 시험방법(S-QI-L05)'}}
};
/* 라돈 두 종류의 기본값. KC 로 갔다가 돌아올 때 되돌린다 */
const RADON_DEFAULTS={purpose:'품질 테스트',place:'라돈 측정실',temp:'상온',
                      method:'라돈 및 토론 시험표준 (S-QI-L01)'};
let KID='finished';
const K=()=>KINDS[KID];
/* 지금 자르기 틀의 가로세로 비율. 성적서 종류를 바꾸면 같이 바뀐다.
   쓰는 곳(chooseKind)보다 먼저 만들어 두어야 한다. */
let BOX_ASPECT=KINDS.finished.aspect;
let seq=0;

function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function dropHTML(id,key,label,tag){
  const pho = (key==='photo'||/photo_/.test(key))
    ? `<button type="button" class="edit">다듬기</button><div class="cut">직접 자른 사진</div>`
    : '';
  return `<label class="drop" id="drop_${key}_${id}" data-key="${key}">
    <img class="thumb" alt="">
    <div class="ico">◇</div>
    <div class="lab">${label}</div>
    <div class="tag">${tag}</div>
    <div class="fn"></div>
    ${pho}
    <div class="bad"></div>
    <input type="file" name="${key}_${id}" ${key==='photo'?'accept="image/*"':''}>
  </label>`;
}
function runHTML(id){
  const slots=K().slots;
  if(K().kc) return `<section class="run" data-run="${id}">
    <div class="run-head">
      <div class="run-title"><span class="dot"></span>
        <div><div class="t"></div><div class="c">시험기 프로그램이 저장한 CSV 를 올리세요</div></div></div>
      <button type="button" class="rm" style="visibility:hidden">삭제</button>
    </div>
    <div class="run-body">
      <div class="uploads" style="grid-template-columns:1fr">${
        slots.map(k=>dropHTML(id,k[0],k[1],k[2])).join('')}</div>
    </div>
  </section>`;
  return `<section class="run" data-run="${id}">
    <div class="run-head">
      <div class="run-title"><span class="dot"></span>
        <div><div class="t"></div><div class="c">측정 원본 ${
          slots.filter(x=>x[0]!=='photo').length}종과 시료를 입력하세요</div></div></div>
      <button type="button" class="rm">삭제</button>
    </div>
    <div class="run-body">
      <div class="uploads" style="grid-template-columns:repeat(${slots.length},1fr)">${
        slots.map(k=>dropHTML(id,k[0],k[1],k[2])).join('')}</div>
      <div class="smp">
        <div class="smp-head"><span class="t">이 측정에 함께 넣은 시료</span>
          <span class="n"><span class="cnt">0</span>종</span></div>
        <div class="samples"></div>
        <button type="button" class="addlink">＋ 시료 추가</button>
      </div>
    </div>
  </section>`;
}
function sampleHTML(id){
  const size=K().size;
  return `<div class="smp-row"${size?'':' style="grid-template-columns:26px 1fr 36px"'}>
    <span class="i"></span>
    <input type="text" name="sname_${id}[]" placeholder="${
      size?'모델명 (예: 엘리븐)':'자재명 (예: 켈리 커버 (린넨 스트라이프))'}">
    ${size?`<input type="text" class="sz" name="ssize_${id}[]" placeholder="사이즈 Q / K">`:''}
    <button type="button" class="x" title="삭제">&times;</button>
  </div>`;
}

/* 화면 넘기기. 1단계는 성적서 종류만, 2단계는 그 성적서를 쓰는 곳. */
function goStep(n){
  const one=(n===1);
  $('#step1').hidden=!one;
  $('#step2').hidden=one;
  $('#bar').hidden=one;                 // 아래 실행 바도 2단계에서만
  document.body.classList.toggle('step1',one);
  $('#stepA').classList.toggle('on',one);
  $('#stepB').classList.toggle('on',!one);
  $('#msg').className='msg';
  window.scrollTo({top:0,behavior:'auto'});
}

/* 성적서 종류 고르기.
   같은 종류를 다시 고르면 쓰던 것을 그대로 두고 넘어간다.
   다른 종류로 바꾸면 올린 파일과 시료가 맞지 않으므로 새로 시작한다. */
function chooseKind(k){
  if(!KINDS[k]) return;
  if(k!==KID){
    const dirty=$$('.run').some(r=>
      $$('.drop input',r).some(i=>i.files.length) ||
      $$('.smp-row input[name^="sname"]',r).some(i=>i.value.trim()));
    if(dirty && !confirm('성적서 종류를 바꾸면 올린 파일과 시료가 지워집니다. 바꿀까요?')) return;
    KID=k;
    BOX_ASPECT=KINDS[k].aspect;
    $('#runs').innerHTML=''; seq=0; addRun();
  }
  $('#runHint').textContent=KINDS[k].hint;
  $('#chosenName').textContent=KINDS[k].name;
  const isKC=!!KINDS[k].kc, isKS=!!KINDS[k].ks;
  $('#kcBox').hidden=!(isKC&&!isKS);
  $('#ksBox').hidden=!isKS;
  $('#kcPhotos').hidden=!isKC;
  $$('#kcPhotos .kc-ph').forEach(p=>p.hidden=(p.dataset.kind!==k));
  $$('.kc-only').forEach(e=>e.hidden=!isKC);
  $('#addRun').hidden=isKC;
  const dv=isKC?KINDS[k].defaults:RADON_DEFAULTS;
  Object.entries(dv).forEach(([n,v])=>{
    const el=$(`[name="${n}"]`); if(!el) return;
    // 사용자가 손댄 값은 두고, 다른 종류의 기본값이 남아 있을 때만 바꾼다
    const all=Object.values(KINDS).map(x=>(x.defaults||RADON_DEFAULTS)[n]).concat(RADON_DEFAULTS[n]);
    if(!el.value || all.indexOf(el.value)>=0) el.value=v;
  });
  $('#form [name="method"]').readOnly=isKC;
  goStep(2);
}

const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];

function addRun(){
  const runs=$$('.run');
  if(runs.length>=K().maxRuns) return;
  $('#runs').insertAdjacentHTML('beforeend',runHTML(seq));
  const el=$(`.run[data-run="${seq}"]`);
  if(!K().kc) addSample(el);
  seq++; sync();
}
function removeRun(el){ if($$('.run').length<=1) return; el.remove(); sync(); }
function addSample(runEl){
  const box=$('.samples',runEl);
  if($$('.smp-row',box).length>=MAX_SMP) return;
  box.insertAdjacentHTML('beforeend',sampleHTML(runEl.dataset.run));
  sync();
}
function sync(){
  const runs=$$('.run');
  let smp=0,pho=0;
  runs.forEach((r,i)=>{
    $('.dot',r).textContent=i+1;
    $('.t',r).textContent=(i+1)+'차 측정';
    $('.rm',r).style.visibility=runs.length>1?'visible':'hidden';
    const rows=$$('.smp-row',r);
    rows.forEach((row,j)=>$('.i',row).textContent=j+1);
    if($('.cnt',r)) $('.cnt',r).textContent=rows.length;
    smp+=rows.length;
    if($('.addlink',r)) $('.addlink',r).style.display=rows.length>=MAX_SMP?'none':'inline-block';
    const pi=$('.drop[data-key="photo"] input',r);
    if(pi&&pi.files.length) pho++;
  });
  if(K().kc){
    smp=$('#form [name="sample_title"]').value.trim()?1:0;
    pho=$$('#kcPhotos .kc-ph:not([hidden]) .drop input').filter(i=>i.files.length).length;
    if(typeof markNext==='function') markNext();
  }
  $('#tRuns').textContent=runs.length;
  $('#tSmp').textContent=smp;
  $('#tPho').textContent=pho;
  const mx=K().maxRuns;
  $('#addRun').disabled=runs.length>=mx;
  fillRunSelect();
  $('#addRun').textContent=runs.length>=mx
      ? `측정은 최대 ${mx}회까지입니다` : '＋  측정 회차 추가';
}

/* ── 파일 내용을 살짝 읽어 장비를 알아본다 ── */
function sniff(file){
  return new Promise(res=>{
    const fr=new FileReader();
    fr.onload=()=>{
      const t=fr.result||'';
      if(/^\s*OPT,\d+,\d+,/.test(t.replace(/^\uFEFF/,''))) res('KC');
      else if(/DURRIDGE|RAD7|Data Print/i.test(t)) res('RAD7');
      else if(/FRD400/i.test(t)) res('FRD400');
      else if(/Radon\s?Eye\s?Plus/i.test(t)) res('RadonEye Plus');
      else if(/RadonEye|RD200/i.test(t)) res('RD200');
      else res('');
    };
    fr.onerror=()=>res('');
    fr.readAsText(file.slice(0,8192));
  });
}


async function onFile(drop,file){
  const key=drop.dataset.key;
  drop.classList.remove('mismatch','has-thumb','cropped');
  drop.dataset.cropped='';
  if(!file){drop.classList.remove('filled');$('.fn',drop).textContent='';
            drop._orig=null;sync();return;}
  drop.classList.add('filled');
  $('.ico',drop).textContent='✓';
  $('.fn',drop).textContent=file.name;
  if(key==='solo'){         // 맨 아래 사진 편집기 — 올리는 즉시 편집기를 연다
    SOLO.orig=file; openEditor(file,'solo'); return;
  }
  if(key==='photo'||drop.dataset.pho){
    drop._orig=file;          // 다듬기는 언제나 원본에서 다시 시작한다
    setThumb(drop,file);
  }else{
    const dev=await sniff(file);
    if(dev && K().expect[key] && K().expect[key].indexOf(dev)<0){
      drop.classList.add('mismatch');
      $('.ico',drop).textContent='!';
      $('.bad',drop).textContent=dev+' 파일로 보입니다';
    }
  }
  sync();
}

/* ── 이벤트 위임 ── */
document.addEventListener('click',e=>{
  const ed=e.target.closest('.drop .edit');
  if(ed){ const d=ed.closest('.drop'); e.preventDefault(); e.stopPropagation();
          openEditor(d._orig||$('input',d).files[0],'run',d); return; }
  const rm=e.target.closest('.rm'); if(rm){removeRun(rm.closest('.run'));return;}
  const ad=e.target.closest('.addlink'); if(ad){addSample(ad.closest('.run'));return;}
  const x=e.target.closest('.smp-row .x');
  if(x){const r=x.closest('.run');x.closest('.smp-row').remove();sync();}
});
/* ── KC 사진 한 번에 넣기 ──────────────────────────────────────
   폰에서 뽑은 사진은 파일명이 뒤섞여도 «찍은 시각» 은 순서대로다. JPEG 의 EXIF 에서
   DateTimeOriginal 을 읽어 그 순서로 다섯 줄 3칸에 차례로 앉힌다. EXIF 가 없으면
   파일 수정 시각으로 대신한다. */
function exifTime(file){
  return new Promise(res=>{
    const fr=new FileReader();
    fr.onload=()=>{
      try{
        const v=new DataView(fr.result); let o=2;
        if(v.getUint16(0)!==0xFFD8) return res(null);
        while(o<v.byteLength-4){
          const marker=v.getUint16(o), len=v.getUint16(o+2);
          if(marker===0xFFE1){                              // APP1 (EXIF)
            const tiff=o+10, little=v.getUint16(tiff)===0x4949;
            const g=(p,n)=>n===2?v.getUint16(p,little):v.getUint32(p,little);
            const ifd0=tiff+g(tiff+4,4);
            const scan=(ifd)=>{
              const n=g(ifd,2); let exif=null, dt=null;
              for(let i=0;i<n;i++){
                const e=ifd+2+i*12, tag=g(e,2);
                if(tag===0x8769) exif=tiff+g(e+8,4);
                if(tag===0x9003||(tag===0x0132&&!dt)){        // 촬영 시각 / (없으면) 수정 시각
                  const cnt=g(e+4,4), p=tiff+g(e+8,4);
                  let str=''; for(let k=0;k<Math.min(cnt,19);k++) str+=String.fromCharCode(v.getUint8(p+k));
                  dt=str;
                }
              }
              return {exif,dt};
            };
            const a=scan(ifd0); let dt=a.dt;
            if(a.exif){ const b=scan(a.exif); if(b.dt) dt=b.dt; }
            if(dt){ const m=dt.match(/(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})/);
              if(m) return res(new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]).getTime()); }
            return res(null);
          }
          if((marker&0xFF00)!==0xFF00) break;
          o+=2+len;
        }
      }catch(_){}
      res(null);
    };
    fr.onerror=()=>res(null);
    fr.readAsArrayBuffer(file.slice(0,131072));            // EXIF 는 앞 128KB 안에 있다
  });
}
/* ── 대기 칸 ──
   놓은 사진은 바로 배치하지 않고 대기 칸에 늘어놓는다. 찍은 시각·파일명 같은 추측은
   폰이 둘이거나 다시 찍으면 틀린다. 사람이 썸네일을 보고 누르는 순서가 정답이다. */
const TRAY=[];                 // [{f, url, t}]
let TRAYPICK=null;             // 골라 둔 대기 사진 (그다음 격자 칸을 누르면 그 자리로)
/* KS 육안 판정 접힌 줄: 부적합이 몇 건인지, 어느 항목인지 한 줄로 */
function ksJudgeSum(){
  const el=$('#ksJudgeSum'); if(!el) return;
  const bad=$$('#ksJudge .jrow select').filter(s=>s.value==='부적합')
      .map(s=>s.closest('.jrow').dataset.short);
  el.textContent = bad.length ? `육안 검사 18항목 · 부적합 ${bad.length}건 · ${bad.join(', ')}` : '육안 검사 18항목 · 전부 적합';
  el.classList.toggle('bad',bad.length>0);
}
function slotsAll(){ return $$('#kcPhotos .kc-ph:not([hidden]) .drop'); }
function nextSlot(){ return slotsAll().find(d=>!$('input',d).files.length)||null; }
function markNext(){
  slotsAll().forEach(d=>d.classList.remove('next'));
  const n=nextSlot(); if(n&&TRAY.length) n.classList.add('next');
}
function renderTray(){
  const box=$('#kcTray'), grid=$('#kcTrayGrid');
  box.hidden=!TRAY.length;
  $('#kcTrayN').textContent=TRAY.length;
  grid.innerHTML=TRAY.map((x,i)=>`<div class="tt${x===TRAYPICK?' pick':''}" data-i="${i}" title="${esc(x.f.name)}">
      <img src="${x.url}" alt=""><span class="n">${esc(x.f.name)}</span></div>`).join('');
  markNext(); sync();
}
function trayAdd(files){
  const list=[...files].filter(f=>/^image\//.test(f.type)||/\.(jpe?g|png)$/i.test(f.name));
  list.forEach(f=>TRAY.push({f, url:URL.createObjectURL(f), t:null}));
  renderTray();
  if(list.length) say('ok',`${list.length}장을 대기 칸에 올렸습니다. 사진을 누르면 «다음 자리» 부터 차례로 들어갑니다.`);
}
function trayTake(i){ const x=TRAY.splice(i,1)[0]; if(x&&x.url) URL.revokeObjectURL(x.url); return x?x.f:null; }
function placeFile(d,f){
  const dt=new DataTransfer(); dt.items.add(f); $('input',d).files=dt.files; onFile(d,f);
}
function placeFromTray(i,slot){
  const d=slot||nextSlot();
  if(!d){ say('warn','빈 자리가 없습니다. 먼저 한 장을 빼거나 바꾸세요.'); return; }
  const prev=$('input',d).files[0];
  const f=trayTake(i); if(!f) return;
  if(prev) TRAY.push({f:prev, url:URL.createObjectURL(prev), t:null});   // 있던 사진은 대기 칸으로
  placeFile(d,f); TRAYPICK=null; renderTray();
}
function unplace(d){                                   // 격자에서 빼서 대기 칸으로
  const f=$('input',d).files[0]; if(!f) return;
  TRAY.push({f:d._orig||f, url:URL.createObjectURL(d._orig||f), t:null});
  $('input',d).value=''; onFile(d,null); renderTray();
}
async function trayByTime(){
  if(!TRAY.length) return;
  for(const x of TRAY){ if(x.t==null){ const t=await exifTime(x.f); x.t=(t==null?x.f.lastModified:t); x.exif=t!=null; } }
  TRAY.sort((a,b)=>a.t-b.t);
  let n=0, noExif=TRAY.filter(x=>!x.exif).length;
  while(TRAY.length && nextSlot()){ placeFromTray(0); n++; }
  let m=`${n}장을 찍은 시각 순서로 채웠습니다.`;
  if(TRAY.length) m+=` ${TRAY.length}장은 자리가 없어 대기 칸에 남았습니다.`;
  if(noExif) m+=` ${noExif}장은 촬영 시각이 없어 파일 시각을 썼습니다.`;
  say(TRAY.length?'warn':'ok', m+' 자리가 틀리면 두 장을 차례로 눌러 바꾸세요.');
}
function bulkPhotos(files){ trayAdd(files); }
document.addEventListener('click',e=>{
  const tt=e.target.closest('#kcTrayGrid .tt');
  if(tt){
    const i=+tt.dataset.i;
    if(TRAYPICK===TRAY[i]){ TRAYPICK=null; renderTray(); return; }   // 다시 누르면 취소
    if(e.shiftKey){ TRAYPICK=TRAY[i]; renderTray(); return; }          // Shift: 자리 골라 넣기
    placeFromTray(i); return;
  }
  if(e.target.closest('#kcByTime')){ trayByTime(); return; }
  if(e.target.closest('#kcTrayClear')){
    if(TRAY.length && !confirm('대기 칸의 사진 '+TRAY.length+'장을 비울까요? (격자에 들어간 사진은 그대로)')) return;
    while(TRAY.length) trayTake(0); TRAYPICK=null; renderTray(); return;
  }
  const rm=e.target.closest('#kcPhotos .kc-ph .drop .rmv');
  if(rm){ e.preventDefault(); e.stopPropagation(); unplace(rm.closest('.drop')); return; }
});
/* 두 장 맞바꾸기: 사진 있는 칸을 누르면 고르고, 다음 칸을 누르면 서로 바뀐다 */
let SWAP=null;
function swapDrops(a,b){
  const fa=$('input',a).files[0], fb=$('input',b).files[0];
  const oa=a._orig, ob=b._orig, ca=a.dataset.cropped, cb=b.dataset.cropped;
  const put=(d,f,orig,cr)=>{
    const dt=new DataTransfer(); if(f) dt.items.add(f); $('input',d).files=dt.files;
    onFile(d,f||null); d._orig=orig||null;
    if(f&&cr==='1'){ d.dataset.cropped='1'; d.classList.add('cropped'); }
  };
  put(a,fb,ob,cb); put(b,fa,oa,ca);
}
document.addEventListener('click',e=>{
  const d=e.target.closest('#kcPhotos .kc-ph .drop');
  if(!d){ if(SWAP&&!e.target.closest('#kcPhotos')){ SWAP.classList.remove('pick'); SWAP=null; } return; }
  if(e.target.closest('.edit')||e.target.closest('.rmv')) return;   // 다듬기·빼기 버튼은 그대로
  if(TRAYPICK){ e.preventDefault(); placeFromTray(TRAY.indexOf(TRAYPICK), d); return; }
  if(TRAY.length && !$('input',d).files.length){            // 대기 사진이 있는데 빈 칸을 누르면 첫 장을 넣는다
    e.preventDefault(); placeFromTray(0, d); return; }
  if(!SWAP){
    if(!$('input',d).files.length) return;                  // 빈 칸은 파일 고르기로 넘어간다
    e.preventDefault(); SWAP=d; d.classList.add('pick'); return;
  }
  e.preventDefault();
  if(SWAP!==d) swapDrops(SWAP,d);
  SWAP.classList.remove('pick'); SWAP=null;
});

/* KC 검사 사진: 한 칸에 여러 장을 놓으면 그 줄의 이 칸부터 오른쪽으로 차례로 채운다.
   15장을 하나씩 올리는 수고를 없애기 위한 것. 남는 사진은 버리고 알려준다. */
function spreadPhotos(drop,files){
  const row=drop.closest('.uploads'); if(!row||!drop.dataset.pho||files.length<2) return false;
  const slots=$$('.drop',row); const start=slots.indexOf(drop);
  const targets=slots.slice(start);
  targets.forEach((d,i)=>{
    if(i>=files.length) return;
    const dt=new DataTransfer(); dt.items.add(files[i]); $('input',d).files=dt.files;
    onFile(d,files[i]);
  });
  const over=files.length-targets.length;
  if(over>0) say('warn',`이 줄에는 ${targets.length}칸만 남아 ${over}장은 넣지 않았습니다.`);
  return true;
}
document.addEventListener('change',e=>{
  const js=e.target.closest('.jrow select'); if(js){ js.closest('.jrow').classList.toggle('bad',js.value==='부적합'); ksJudgeSum(); }
  const inp=e.target.closest('.drop input');
  if(!inp) return;
  const d=inp.closest('.drop');
  if(d.dataset.key==='kbulk'){ bulkPhotos(inp.files); inp.value=''; return; }
  if(inp.files.length>1 && spreadPhotos(d,[...inp.files])) return;
  onFile(d, inp.files[0]);
});
['dragenter','dragover'].forEach(ev=>document.addEventListener(ev,e=>{
  const d=e.target.closest('.drop'); if(!d)return;
  e.preventDefault(); d.classList.add('over');
}));
['dragleave','drop'].forEach(ev=>document.addEventListener(ev,e=>{
  const d=e.target.closest('.drop'); if(!d)return;
  d.classList.remove('over');
}));
document.addEventListener('drop',e=>{
  const d=e.target.closest('.drop'); if(!d)return;
  e.preventDefault();
  if(d.dataset.key==='kbulk'){ bulkPhotos(e.dataTransfer.files); return; }
  if(e.dataTransfer.files.length>1 && spreadPhotos(d,[...e.dataTransfer.files])) return;
  const f=e.dataTransfer.files[0]; if(!f)return;
  const inp=$('input',d);
  const dt=new DataTransfer(); dt.items.add(f); inp.files=dt.files;
  onFile(d,f);
});
$('#addRun').addEventListener('click',addRun);
addRun();
goStep(1);                               // 첫 화면은 성적서 고르기

/* ── 사진 다듬기 ────────────────────────────────────────────────
   자르기 틀은 성적서 사진칸과 똑같은 모양(BOX_ASPECT)이다. 그래서 여기서 고른
   자리가 성적서에 그대로 들어간다. 처음 자리는 프로그램이 혼자 고르는 자리
   (ROI)와 같게 잡아, 대개는 확인만 하고 지나가면 된다.
   맨 아래 «사진 편집기»에서 열면 비율을 자유롭게 고르고 내려받을 수 있다. */
const ROI={{photo_roi}};
const ED={mode:'run',drop:null,src:null,rot:0,scale:1,rect:null,url:null,
          aspect:BOX_ASPECT,file:null};
$('#kinds').addEventListener('click',e=>{
  const c=e.target.closest('.kind'); if(c) chooseKind(c.dataset.kind);
});
$('#back').addEventListener('click',()=>goStep(1));
const SOLO={orig:null,file:null,url:null,name:'사진.jpg',ratio:BOX_ASPECT};

function setThumb(drop,file){
  const img=$('.thumb',drop);
  if(img.dataset.url) URL.revokeObjectURL(img.dataset.url);
  const u=URL.createObjectURL(file);
  img.dataset.url=u; img.src=u;
  drop.classList.add('has-thumb');
}

/* 돌린 결과를 원래 해상도 그대로 담아 둔다 */
function makeSource(img,rot){
  const q=((rot%4)+4)%4, w=img.naturalWidth, h=img.naturalHeight;
  const c=document.createElement('canvas');
  c.width = q%2 ? h : w; c.height = q%2 ? w : h;
  const x=c.getContext('2d');
  x.translate(c.width/2,c.height/2); x.rotate(q*Math.PI/2);
  x.drawImage(img,-w/2,-h/2);
  return c;
}

/* core.crop_to_box 와 같은 셈 — 프로그램이 혼자 고르는 자리.
   비율을 안 정했으면(자유) 사진 전체를 잡는다. */
function defaultRect(sw,sh,a){
  if(!a) return {x:0,y:0,w:sw,h:sh};
  const x0=sw*ROI[0], y0=sh*ROI[1], x1=sw*ROI[2], y1=sh*ROI[3];
  const cw=Math.max(1,x1-x0), ch=Math.max(1,y1-y0);
  const cx=(x0+x1)/2, cy=(y0+y1)/2;
  let nw,nh;
  if(cw/ch<a){ nh=ch; nw=ch*a; } else { nw=cw; nh=cw/a; }
  if(nw>sw){ nw=sw; nh=sw/a; }
  if(nh>sh){ nh=sh; nw=sh*a; }
  return {x:Math.max(0,Math.min(cx-nw/2,sw-nw)),
          y:Math.max(0,Math.min(cy-nh/2,sh-nh)), w:nw, h:nh};
}

function layout(){
  const c=ED.src; if(!c) return;
  const cv=$('#cv');
  if(cv.width!==c.width||cv.height!==c.height){
    cv.width=c.width; cv.height=c.height;
    cv.getContext('2d').drawImage(c,0,0);
  }
  const availW=Math.min(940,window.innerWidth-48)-32;
  const availH=Math.max(200,window.innerHeight-360);
  ED.scale=Math.min(availW/c.width, availH/c.height);
  cv.style.width=(c.width*ED.scale)+'px';
  cv.style.height=(c.height*ED.scale)+'px';
  drawBox(); drawMarks();
}
function drawBox(){
  const r=ED.rect, s=ED.scale, b=$('#cropbox');
  b.style.left=(r.x*s)+'px'; b.style.top=(r.y*s)+'px';
  b.style.width=(r.w*s)+'px'; b.style.height=(r.h*s)+'px';
  const n=$('#edSize');
  if(n) n.textContent=Math.round(r.w)+' × '+Math.round(r.h);
}

/* ── 사진에 표시하기 ──────────────────────────────────────────
   도형을 원본 사진에 바로 굽지 않는다. 좌표는 «원본 사진의 픽셀» 로만 들고
   있다가, 확정할 때 한 번에 합성한다. 미리보기도 원본 크기 캔버스에 그린 뒤
   CSS 로 줄여 보여주므로, 화면에서 본 모습과 결과물이 정확히 같다.
   (화면 좌표로 저장하면 축소본 기준이라 최종 사진에서 자리가 틀어진다.) */
const COLORS=['#e8112d','#f47b20','#ffd200','#1faa4b','#1668dc','#0b0b0c','#ffffff'];
const MARK={tool:'arrow',color:COLORS[0],w:'mid',
            items:[],undo:[],redo:[],sel:-1,draft:null};

function markUnit(){                       // 사진 크기에 맞춘 기준 굵기(원본 픽셀)
  const c=ED.src; return c ? Math.max(2,Math.min(c.width,c.height)/220) : 3;
}
function markW(){
  return markUnit()*(MARK.w==='thin'?0.6:MARK.w==='bold'?2.2:1.2);
}

/* ── 그리기 */
function paintOne(x,it){
  x.save();
  x.strokeStyle=it.color; x.fillStyle=it.color;
  x.lineWidth=it.w; x.lineCap='round'; x.lineJoin='round';
  if(it.type==='rect'){
    x.strokeRect(it.x,it.y,it.w2,it.h2);
  }else if(it.type==='ellipse'){
    x.beginPath();
    x.ellipse(it.x+it.w2/2,it.y+it.h2/2,Math.abs(it.w2/2),Math.abs(it.h2/2),0,0,Math.PI*2);
    x.stroke();
  }else if(it.type==='pen'){
    x.beginPath();
    it.pts.forEach((p,i)=> i?x.lineTo(p[0],p[1]):x.moveTo(p[0],p[1]));
    x.stroke();
  }else if(it.type==='text'){
    x.font='600 '+it.size+'px Pretendard, system-ui, sans-serif';
    x.textBaseline='top';
    x.fillText(it.text,it.x,it.y);
  }else{                                   // 화살표
    const a=Math.atan2(it.y2-it.y1,it.x2-it.x1);
    const len=Math.hypot(it.x2-it.x1,it.y2-it.y1);
    const head=Math.min(len*0.34, it.w*4.5);
    const bx=it.x2-Math.cos(a)*head*0.82, by=it.y2-Math.sin(a)*head*0.82;
    x.beginPath(); x.moveTo(it.x1,it.y1); x.lineTo(bx,by); x.stroke();
    x.beginPath();
    x.moveTo(it.x2,it.y2);
    x.lineTo(it.x2-Math.cos(a-0.42)*head, it.y2-Math.sin(a-0.42)*head);
    x.lineTo(it.x2-Math.cos(a+0.42)*head, it.y2-Math.sin(a+0.42)*head);
    x.closePath(); x.fill();
  }
  x.restore();
}

function markBox(it){                      // 도형을 감싸는 네모 (원본 좌표)
  if(it.type==='arrow')
    return {x:Math.min(it.x1,it.x2),y:Math.min(it.y1,it.y2),
            w:Math.abs(it.x2-it.x1),h:Math.abs(it.y2-it.y1)};
  if(it.type==='pen'){
    const xs=it.pts.map(p=>p[0]), ys=it.pts.map(p=>p[1]);
    return {x:Math.min.apply(null,xs),y:Math.min.apply(null,ys),
            w:Math.max.apply(null,xs)-Math.min.apply(null,xs),
            h:Math.max.apply(null,ys)-Math.min.apply(null,ys)};
  }
  if(it.type==='text')
    return {x:it.x,y:it.y,w:it.size*0.62*(it.text.length||1),h:it.size*1.2};
  return {x:Math.min(it.x,it.x+it.w2),y:Math.min(it.y,it.y+it.h2),
          w:Math.abs(it.w2),h:Math.abs(it.h2)};
}

function paintMarks(x,items,draft,sel){
  items.forEach((it,i)=>{
    paintOne(x,it);
    if(i===sel){
      const b=markBox(it), p=Math.max(6,it.w*1.5);
      x.save(); x.strokeStyle='#1668dc'; x.lineWidth=Math.max(1.5,it.w*0.5);
      x.setLineDash([p*1.4,p]);
      x.strokeRect(b.x-p,b.y-p,b.w+p*2,b.h+p*2); x.restore();
    }
  });
  if(draft) paintOne(x,draft);
}

function drawMarks(){
  const c=ED.src, mk=$('#mk'); if(!c||!mk) return;
  if(mk.width!==c.width||mk.height!==c.height){ mk.width=c.width; mk.height=c.height; }
  mk.style.width=(c.width*ED.scale)+'px';
  mk.style.height=(c.height*ED.scale)+'px';
  const x=mk.getContext('2d');
  x.clearRect(0,0,mk.width,mk.height);
  paintMarks(x,MARK.items,MARK.draft,MARK.sel);
}

/* ── 되돌리기 */
function markPush(){
  MARK.undo.push(JSON.stringify(MARK.items));
  if(MARK.undo.length>60) MARK.undo.shift();
  MARK.redo.length=0;
}
function markUndo(){
  if(!MARK.undo.length) return;
  MARK.redo.push(JSON.stringify(MARK.items));
  MARK.items=JSON.parse(MARK.undo.pop());
  MARK.sel=-1; drawMarks(); markBtns();
}
function markRedo(){
  if(!MARK.redo.length) return;
  MARK.undo.push(JSON.stringify(MARK.items));
  MARK.items=JSON.parse(MARK.redo.pop());
  MARK.sel=-1; drawMarks(); markBtns();
}
function markDel(){
  if(MARK.sel<0) return;
  markPush(); MARK.items.splice(MARK.sel,1); MARK.sel=-1;
  drawMarks(); markBtns();
}
function markClear(){
  if(!MARK.items.length) return;
  if(!confirm('표시한 것을 모두 지웁니다. 계속할까요?')) return;
  markPush(); MARK.items=[]; MARK.sel=-1; drawMarks(); markBtns();
}
function markReset(){
  MARK.items=[]; MARK.undo=[]; MARK.redo=[]; MARK.sel=-1; MARK.draft=null;
}
function markBtns(){
  $('#mDel').disabled  = MARK.sel<0;
  $('#mUndo').disabled = !MARK.undo.length;
  $('#mRedo').disabled = !MARK.redo.length;
  const n=$('#markCount');
  if(n) n.textContent=MARK.items.length;
}

/* ── 마우스 */
function markPt(e){
  const b=$('#mk').getBoundingClientRect(), c=ED.src;
  return {x:Math.max(0,Math.min((e.clientX-b.left)/ED.scale,c.width)),
          y:Math.max(0,Math.min((e.clientY-b.top )/ED.scale,c.height))};
}
function markHit(px,py){                   // 위에 있는 것부터 찾는다
  for(let i=MARK.items.length-1;i>=0;i--){
    const b=markBox(MARK.items[i]), p=Math.max(8,MARK.items[i].w*2);
    if(px>=b.x-p&&px<=b.x+b.w+p&&py>=b.y-p&&py<=b.y+b.h+p) return i;
  }
  return -1;
}
function markMove(it,dx,dy){
  if(it.type==='arrow'){ it.x1+=dx; it.y1+=dy; it.x2+=dx; it.y2+=dy; }
  else if(it.type==='pen'){ it.pts=it.pts.map(p=>[p[0]+dx,p[1]+dy]); }
  else { it.x+=dx; it.y+=dy; }
}

let MDRAG=null;
function markDown(e){
  if(!MARK_ON||!ED.src) return;
  e.preventDefault();
  const p=markPt(e);
  const hit=markHit(p.x,p.y);
  if(hit>=0){                              // 그려 둔 것 위 -> 고르고 옮기기
    MARK.sel=hit; markBtns(); drawMarks();
    MDRAG={kind:'move',px:p.x,py:p.y,before:JSON.stringify(MARK.items)};
    $('#mk').setPointerCapture(e.pointerId);
    return;
  }
  MARK.sel=-1; markBtns();
  if(MARK.tool==='text'){
    const t=(prompt('넣을 글자를 적으세요','')||'').trim();
    if(t){ markPush();
      MARK.items.push({type:'text',x:p.x,y:p.y,text:t,color:MARK.color,
                       w:markW(),size:markW()*6}); }
    drawMarks(); markBtns(); return;
  }
  const w=markW();
  MARK.draft = MARK.tool==='pen'
    ? {type:'pen',pts:[[p.x,p.y]],color:MARK.color,w:w}
    : MARK.tool==='arrow'
      ? {type:'arrow',x1:p.x,y1:p.y,x2:p.x,y2:p.y,color:MARK.color,w:w}
      : {type:MARK.tool,x:p.x,y:p.y,w2:0,h2:0,color:MARK.color,w:w};
  MDRAG={kind:'draw',px:p.x,py:p.y};
  $('#mk').setPointerCapture(e.pointerId);
  drawMarks();
}
function markDrag(e){
  if(!MDRAG||!ED.src) return;
  const p=markPt(e);
  if(MDRAG.kind==='move'){
    const it=MARK.items[MARK.sel]; if(!it) return;
    markMove(it,p.x-MDRAG.px,p.y-MDRAG.py);
    MDRAG.px=p.x; MDRAG.py=p.y;
  }else{
    const d=MARK.draft; if(!d) return;
    if(d.type==='pen'){ d.pts.push([p.x,p.y]); }
    else if(d.type==='arrow'){ d.x2=p.x; d.y2=p.y; }
    else { d.x=Math.min(MDRAG.px,p.x); d.y=Math.min(MDRAG.py,p.y);
           d.w2=Math.abs(p.x-MDRAG.px); d.h2=Math.abs(p.y-MDRAG.py); }
  }
  drawMarks();
}
function markUp(){
  if(!MDRAG) return;
  if(MDRAG.kind==='move'){
    if(MDRAG.before!==JSON.stringify(MARK.items)){
      MARK.undo.push(MDRAG.before);
      if(MARK.undo.length>60) MARK.undo.shift();
      MARK.redo.length=0;
    }
  }else{
    const d=MARK.draft;
    const big = d && (d.type==='pen' ? d.pts.length>2
              : d.type==='arrow' ? Math.hypot(d.x2-d.x1,d.y2-d.y1)>markUnit()*3
              : Math.abs(d.w2)>markUnit()*3 && Math.abs(d.h2)>markUnit()*3);
    if(big){ markPush(); MARK.items.push(d); }
  }
  MARK.draft=null; MDRAG=null; drawMarks(); markBtns();
}

/* ── 탭 */
let MARK_ON=false;
function setTab(which){
  MARK_ON = which==='mark';
  $('#mask').classList.toggle('mark-mode',MARK_ON);
  $('#tabCrop').classList.toggle('on',!MARK_ON);
  $('#tabMark').classList.toggle('on', MARK_ON);
  $('#mk').style.pointerEvents = MARK_ON ? 'auto' : 'none';
  $('#edOk').textContent = MARK_ON ? '표시한 대로 확정' : '이 자리로 자르기';
  if(!MARK_ON){ MARK.sel=-1; }
  drawMarks(); markBtns();
}

/* 비율 바꾸기. 지금 보고 있는 자리의 한가운데를 지키며 새 모양으로 고쳐 잡는다 */
function setAspect(key){
  ED.aspect = key==='box' ? BOX_ASPECT : (key==='0' ? null : parseFloat(key));
  $$('#ratios button').forEach(b=>b.classList.toggle('on',b.dataset.a===key));
  if(!ED.src) return;
  const sw=ED.src.width, sh=ED.src.height, r=ED.rect;
  if(!ED.aspect){ drawBox(); return; }
  const cx=r.x+r.w/2, cy=r.y+r.h/2;
  let w=r.w, h=w/ED.aspect;
  if(h>sh){ h=sh; w=sh*ED.aspect; }
  if(w>sw){ w=sw; h=sw/ED.aspect; }
  ED.rect={x:Math.max(0,Math.min(cx-w/2,sw-w)),
           y:Math.max(0,Math.min(cy-h/2,sh-h)), w:w, h:h};
  drawBox();
}

function openEditor(file,mode,drop){
  if(!file) return;
  ED.mode=mode||'run'; ED.drop=drop||null; ED.file=file; ED.rot=0;
  markReset(); setTab('crop');
  $('#mask').classList.toggle('solo-mode',ED.mode==='solo');
  if(ED.mode==='run') setAspect('box');
  const img=new Image();
  img.onload=()=>{
    ED.src=makeSource(img,0);
    ED.rect=defaultRect(ED.src.width,ED.src.height,ED.aspect);
    $('#cv').width=0;
    $('#mask').classList.add('on');
    layout();
  };
  img.onerror=()=>say('err','사진을 화면에 열 수 없습니다. JPG 또는 PNG 로 올려주세요.');
  if(ED.url) URL.revokeObjectURL(ED.url);
  ED.url=URL.createObjectURL(file);
  img.src=ED.url;
}
function closeEditor(){
  $('#mask').classList.remove('on');
  if(ED.url){ URL.revokeObjectURL(ED.url); ED.url=null; }
  ED.drop=null; ED.src=null; ED.file=null;
  markReset();
}
function rotate(dir){
  if(!ED.file) return;
  // 사진을 돌리면 원본 좌표계가 통째로 바뀐다. 표시한 자리를 그대로 옮길
  // 방법이 없으므로 먼저 물어본다.
  if(MARK.items.length &&
     !confirm('사진을 돌리면 표시한 내용이 지워집니다. 계속할까요?')) return;
  markReset();
  const img=new Image();
  img.onload=()=>{
    ED.rot+=dir;
    ED.src=makeSource(img,ED.rot);
    ED.rect=defaultRect(ED.src.width,ED.src.height,ED.aspect);
    $('#cv').width=0;                       // 크기가 바뀌었으니 다시 그린다
    layout();
  };
  img.src=ED.url;
}

/* 끌어서 옮기고 늘이기 */
let DRAG=null;
$('#cbox').addEventListener('pointerdown',e=>{
  if(!ED.src) return;
  const g=e.target.dataset&&e.target.dataset.g;
  if(!g && !e.target.closest('#cropbox')) return;
  e.preventDefault(); e.target.setPointerCapture(e.pointerId);
  DRAG={grip:g||'move', px:e.clientX, py:e.clientY, r:Object.assign({},ED.rect)};
});
$('#cbox').addEventListener('pointermove',e=>{
  if(!DRAG) return;
  const s=ED.scale, sw=ED.src.width, sh=ED.src.height, A=ED.aspect;
  const dx=(e.clientX-DRAG.px)/s, dy=(e.clientY-DRAG.py)/s, o=DRAG.r, g=DRAG.grip;
  const r=ED.rect, bx=o.x+o.w, by=o.y+o.h;
  const minw=Math.max(48,sw*0.05), minh=Math.max(48,sh*0.05);
  if(g==='move'){
    r.x=Math.max(0,Math.min(o.x+dx,sw-o.w));
    r.y=Math.max(0,Math.min(o.y+dy,sh-o.h));
    r.w=o.w; r.h=o.h;
  }else if(A){                       // 비율을 지키며 늘인다
    let w, lim;
    if(g==='se'){ w=o.w+dx; lim=Math.min(sw-o.x,(sh-o.y)*A); }
    else if(g==='ne'){ w=o.w+dx; lim=Math.min(sw-o.x, by*A); }
    else if(g==='sw'){ w=o.w-dx; lim=Math.min(bx,(sh-o.y)*A); }
    else             { w=o.w-dx; lim=Math.min(bx, by*A); }
    w=Math.max(minw,Math.min(w,lim)); const h=w/A;
    r.w=w; r.h=h;
    r.x=(g==='sw'||g==='nw') ? bx-w : o.x;
    r.y=(g==='nw'||g==='ne') ? by-h : o.y;
  }else{                             // 자유 비율 — 네 변을 따로 움직인다
    let x1=o.x, y1=o.y, x2=bx, y2=by;
    if(g.indexOf('e')>=0) x2=Math.min(sw,Math.max(o.x+minw,bx+dx));
    if(g.indexOf('w')>=0) x1=Math.max(0,Math.min(bx-minw,o.x+dx));
    if(g.indexOf('s')>=0) y2=Math.min(sh,Math.max(o.y+minh,by+dy));
    if(g.indexOf('n')>=0) y1=Math.max(0,Math.min(by-minh,o.y+dy));
    r.x=x1; r.y=y1; r.w=x2-x1; r.h=y2-y1;
  }
  drawBox();
});
['pointerup','pointercancel'].forEach(ev=>
  $('#cbox').addEventListener(ev,()=>{DRAG=null;}));

function applyCrop(){
  const d=ED.drop, mode=ED.mode, r=ED.rect, c=ED.src;
  const k=Math.min(1,1600/Math.max(r.w,r.h));
  const ow=Math.max(1,Math.round(r.w*k));
  const oh=ED.aspect ? Math.max(1,Math.round(ow/ED.aspect))
                     : Math.max(1,Math.round(r.h*k));
  const o=document.createElement('canvas'); o.width=ow; o.height=oh;
  const x=o.getContext('2d'); x.imageSmoothingQuality='high';
  x.drawImage(c, r.x,r.y,r.w,r.h, 0,0,ow,oh);
  // 표시는 여기서 «처음으로» 사진에 얹힌다. 좌표가 원본 기준이라
  // 자른 자리를 빼고 같은 배율을 곱하면 화면에서 본 그대로가 된다.
  if(MARK.items.length){
    x.save();
    x.beginPath(); x.rect(0,0,ow,oh); x.clip();      // 사진 밖으로는 안 나가게
    x.scale(ow/r.w, oh/r.h); x.translate(-r.x,-r.y);
    paintMarks(x, MARK.items, null, -1);
    x.restore();
  }
  const base=((ED.file&&ED.file.name)||'photo').replace(/\.[^.]+$/,'');
  o.toBlob(blob=>{
    if(!blob){ say('err','사진을 자르지 못했습니다.'); return; }
    const f=new File([blob],base+(MARK.items.length?'_표시':'_자름')+'.jpg',
                     {type:'image/jpeg'});
    if(mode==='run'){
      const dt=new DataTransfer(); dt.items.add(f);
      $('input',d).files=dt.files;
      d.dataset.cropped='1'; d.classList.add('cropped');
      $('.fn',d).textContent=f.name;
      setThumb(d,f);
    }else{
      soloDone(f,ow,oh);
    }
    closeEditor();
  },'image/jpeg',0.92);
}

/* 맨 아래 사진 편집기 — 자른 결과를 보여주고 내려받게 한다 */
function soloDone(f,ow,oh){
  const box=$('#soloOut');
  if(SOLO.url) URL.revokeObjectURL(SOLO.url);
  SOLO.url=URL.createObjectURL(f); SOLO.name=f.name;
  SOLO.file=f; SOLO.ratio=ow/oh;
  $('.out-img',box).src=SOLO.url;
  $('.out-meta',box).textContent=
    ow+' × '+oh+' 화소  ·  '+(f.size/1024).toFixed(0)+' KB';
  box.classList.add('done');
  fillRunSelect();
}

/* 넣을 측정 회차 목록을 채운다 (측정을 더하거나 지우면 다시 부른다) */
function fillRunSelect(){
  const sel=$('#soloRun'); if(!sel) return;
  const cur=sel.value;
  if(K().kc){
    sel.innerHTML=$$('#kcPhotos .kc-ph:not([hidden]) .drop').map(d=>{
      const has=$('input',d).files.length, m=d.dataset.key.match(/photo_(\d+)_(\d)/);
      const nm=$('.kc-ph-t',d.closest('.kc-ph')).textContent.replace(/^\d+/,'').trim();
      return '<option value="'+d.id+'">'+nm+' · 사진 '+(parseInt(m[2],10)+1)+(has?' — 바꾸기':'')+'</option>';
    }).join('');
  }else
  sel.innerHTML=$$('.run').map((r,i)=>{
    const pi=$('.drop[data-key="photo"] input',r);
    const has=pi&&pi.files.length;
    return '<option value="'+i+'">'+(i+1)+'차 측정'+(has?' — 지금 사진과 바꾸기':'')+'</option>';
  }).join('');
  if(cur && sel.querySelector('option[value="'+cur+'"]')) sel.value=cur;
}

/* 편집한 사진을 그 측정의 시료 사진 칸에 그대로 앉힌다 */
function putIntoRun(){
  if(!SOLO.file){ say('err','먼저 사진을 다듬어 주세요.'); return; }
  const val=$('#soloRun').value;
  const i=parseInt(val,10);
  const r=K().kc ? document.getElementById(val) : $$('.run')[i];
  if(!r){ say('err','넣을 자리가 없습니다.'); return; }
  const d=K().kc ? r : $('.drop[data-key="photo"]',r);
  const dt=new DataTransfer(); dt.items.add(SOLO.file);
  $('input',d).files=dt.files;
  d._orig=SOLO.file;                 // 여기서 [다듬기] 를 누르면 이 사진에서 이어 간다
  d.dataset.cropped='1';
  d.classList.add('filled','cropped','has-thumb');
  d.classList.remove('mismatch');
  $('.ico',d).textContent='✓';
  $('.fn',d).textContent=SOLO.file.name;
  setThumb(d,SOLO.file);
  sync();
  r.classList.remove('flash'); void r.offsetWidth; r.classList.add('flash');
  r.scrollIntoView({behavior:'smooth',block:'center'});
  // 성적서 사진칸과 비율이 다르면 그만큼은 성적서에서 잘린다. 미리 알려준다.
  const off=SOLO.ratio/BOX_ASPECT;
  let note='';
  if(off<0.99) note=' 다만 세로가 길어 성적서에서는 위아래가 조금 잘립니다.';
  else if(off>1.01) note=' 다만 가로가 길어 성적서에서는 좌우가 조금 잘립니다.';
  say(note?'warn':'ok', (K().kc?'검사 사진 칸에':(i+1)+'차 측정의 시료 사진으로')+' 넣었습니다.'+note);
}
$('#soloPut').addEventListener('click',putIntoRun);
$('#soloEdit').addEventListener('click',()=>openEditor(SOLO.orig,'solo'));
$('#soloSave').addEventListener('click',()=>{
  if(!SOLO.url) return;
  const a=document.createElement('a');
  a.href=SOLO.url; a.download=SOLO.name; a.click();
});

$('#edX').addEventListener('click',closeEditor);
$('#edCancel').addEventListener('click',closeEditor);
$('#edOk').addEventListener('click',applyCrop);
$('#edReset').addEventListener('click',()=>{
  if(!ED.src) return;
  ED.rect=defaultRect(ED.src.width,ED.src.height,ED.aspect); drawBox();
});
$$('#mask [data-rot]').forEach(b=>
  b.addEventListener('click',()=>rotate(+b.dataset.rot)));
$$('#ratios button').forEach(b=>
  b.addEventListener('click',()=>setAspect(b.dataset.a)));
$('#mask').addEventListener('pointerdown',e=>{ if(e.target.id==='mask') closeEditor(); });

/* 표시하기 — 탭 · 도구 · 색 · 굵기 · 편집 */
$('#tabCrop').addEventListener('click',()=>setTab('crop'));
$('#tabMark').addEventListener('click',()=>setTab('mark'));
COLORS.forEach((c,i)=>{
  const b=document.createElement('button');
  b.type='button'; b.className='sw'+(i?'':' on'); b.dataset.c=c;
  b.style.background=c;
  b.title=['빨강','주황','노랑','초록','파랑','검정','흰색'][i];
  $('#swatches').appendChild(b);
});
$('#swatches').addEventListener('click',e=>{
  const b=e.target.closest('.sw'); if(!b) return;
  MARK.color=b.dataset.c;
  $$('#swatches .sw').forEach(o=>o.classList.toggle('on',o===b));
});
$('#markbar').addEventListener('click',e=>{
  const t=e.target.closest('.mt'), w=e.target.closest('.mw');
  if(t){ MARK.tool=t.dataset.t; $$('#markbar .mt').forEach(o=>o.classList.toggle('on',o===t)); }
  if(w){ MARK.w=w.dataset.w; $$('#markbar .mw').forEach(o=>o.classList.toggle('on',o===w)); }
});
$('#mDel').addEventListener('click',markDel);
$('#mUndo').addEventListener('click',markUndo);
$('#mRedo').addEventListener('click',markRedo);
$('#mClear').addEventListener('click',markClear);
$('#mk').addEventListener('pointerdown',markDown);
$('#mk').addEventListener('pointermove',markDrag);
['pointerup','pointercancel'].forEach(ev=>$('#mk').addEventListener(ev,markUp));
document.addEventListener('keydown',e=>{
  if(!$('#mask').classList.contains('on')||!MARK_ON) return;
  const z=e.ctrlKey||e.metaKey, k=(e.key||'').toLowerCase();
  if(z&&k==='z'){ e.preventDefault(); markUndo(); }
  else if(z&&k==='y'){ e.preventDefault(); markRedo(); }
  else if((e.key==='Delete'||e.key==='Backspace')&&MARK.sel>=0){
    e.preventDefault(); markDel(); }
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&$('#mask').classList.contains('on')) closeEditor();
});
window.addEventListener('resize',()=>{ if(ED.src) layout(); });

/* 내려가면 맨 위 띠가 떠 있다는 걸 실선 하나로 알린다 */
const topbar=document.querySelector('.topbar');
const onScroll=()=>{ if(topbar) topbar.classList.toggle('float',window.scrollY>6); };
window.addEventListener('scroll',onScroll,{passive:true}); onScroll();

/* ── 제출 ── */
function say(kind,text){
  const m=$('#msg'); m.className='msg show '+kind; $('#msgin').textContent=text;
  if(kind!=='err') setTimeout(()=>m.classList.remove('show'),9000);
}
$('#form').addEventListener('submit',async function(e){
  e.preventDefault();
  const btn=$('#gen'), runs=$$('.run');
  let total=0;
  const need=K().slots.filter(sl=>sl[0]!=='photo').map(sl=>sl[0]);
  if(!K().kc) for(const [i,r] of runs.entries()){
    for(const k of need){
      const inp=$(`.drop[data-key="${k}"] input`,r);
      if(!inp||!inp.files.length){
        say('err',`${i+1}번째 측정: ${K().nice[k]} 파일을 올려주세요.`); return;
      }
    }
    const names=$$('.smp-row input[name^="sname"]',r).filter(x=>x.value.trim());
    if(!names.length){ say('err',`${i+1}번째 측정: 시료 이름을 최소 1개 입력해주세요.`); return; }
    total+=names.length;
  }
  if(total>MAX_TOTAL){ say('err',`시료는 최대 ${MAX_TOTAL}종까지입니다. (현재 ${total}종)`); return; }

  const fd=new FormData();
  fd.append('kind',KID);
  if($('#practice').checked) fd.append('practice','1');
  if($('#backdated').checked) fd.append('backdated','1');
  { const iss=$('[name="issuer"]',this); if(iss){ fd.append('issuer',iss.value); try{localStorage.setItem('issuer',iss.value);}catch(e){} } }
  { const rb=document.getElementById('reissueBox'); const rs=$('[name="reissue_reason"]',this); if(rb&&!rb.hidden&&rs) fd.append('reissue_reason',rs.value); }
  ['report_no','sample_title','purpose','request_date','issue_date','place','temp','humid','method']
    .forEach(n=>{const el=$(`[name="${n}"]`,this); if(el) fd.append(n,el.value);});
  if(K().kc){
    const inp=$('.drop[data-key="csv"] input',runs[0]);
    if(!inp||!inp.files.length){ say('err','내구시험기 CSV 파일을 올려주세요.'); return; }
    fd.append('csv_0',inp.files[0]);
    const names = K().ks
      ? ['test_date','ks_dim_w','ks_dim_l','ks_dim_t','ks_spec_w','ks_spec_l','ks_spec_t','ks_fabric','ks_dims_judge',
         ...$$('#ksBox select[name^="ks_judge_"]').map(e=>e.name)]
      : ['test_date','last_cycle','dim_w','dim_l','dim_t','fabric',
         'judge_appearance','judge_dims','judge_material','judge_durability','judge_fabric'];
    names.forEach(n=>{const el=$(`[name="${n}"]`,this); if(el) fd.append(n,el.value);});
    $$('#kcPhotos .kc-ph:not([hidden]) .drop').forEach(d=>{
      const f=$('input',d).files[0]; if(!f) return;
      fd.append(d.dataset.key,f);
      if(d.dataset.cropped==='1') fd.append(d.dataset.key.replace('photo','crop'),'1');
    });
  }else
  runs.forEach((r,i)=>{
    K().slots.forEach(([k])=>{
      const f=$(`.drop[data-key="${k}"] input`,r);
      if(f&&f.files[0]) fd.append(`${k}_${i}`,f.files[0]);
    });
    const pd=$('.drop[data-key="photo"]',r);
    if(pd && pd.dataset.cropped==='1') fd.append(`crop_${i}`,'1');
    $$('.smp-row',r).forEach(row=>{
      const nm=$('input[name^="sname"]',row).value.trim();
      if(!nm) return;
      const sz=$('input[name^="ssize"]',row);
      fd.append(`sname_${i}[]`,nm);
      fd.append(`ssize_${i}[]`,sz?sz.value.trim():'');
    });
  });
  fd.append('n_runs',runs.length);

  btn.disabled=true; const old=btn.textContent; btn.textContent='입력 점검 중 …';
  $('#msg').className='msg';
  try{
    // 생성 전 입력 점검 — 경고가 있으면 확인을 받는다 (생성은 막지 않는다)
    let warnItems=[];
    try{ const pc=await (await fetch('/성적서/점검',{method:'POST',body:fd})).json(); warnItems=(pc&&pc.warnings)||[]; }catch(_){ warnItems=[]; }
    if(warnItems.length){
      const go=await askWarnings(warnItems);
      if(!go){ say('warn','입력을 고친 뒤 다시 누르세요.'); return; }
      fd.append('ack_warnings','1'); fd.append('warn_items',JSON.stringify(warnItems.map(w=>w.what)));
    }
    btn.textContent='생 성 중 …';
    const res=await fetch('/generate',{method:'POST',body:fd});
    if(!res.ok){
      let m='서버 오류 ('+res.status+')';
      try{const j=await res.json(); if(j&&j.error) m=j.error;}catch(_){}
      throw new Error(m);
    }
    const blob=await res.blob();
    const cd=res.headers.get('Content-Disposition')||'';
    let name='성적서.xlsx';
    let m=cd.match(/filename\*=UTF-8''([^;]+)/i);
    if(m){ name=decodeURIComponent(m[1]); }
    else { m=cd.match(/filename="?([^";]+)"?/i); if(m) name=m[1]; }
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=url; a.download=name; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),4000);
    const warn=res.headers.get('X-Report-Warning');
    if(warn) say('warn','성적서가 생성되었습니다. 다만 '+decodeURIComponent(warn));
    else if(fd.get('ack_warnings')) say('warn',`성적서가 생성되었습니다 — ${name}. 입력 경고 ${JSON.parse(fd.get('warn_items')).length}건을 확인하고 만든 것으로 기록에 남깁니다.`);
    else say('ok',`성적서가 생성되었습니다 — ${name}`);
  }catch(err){ say('err',err.message); }
  finally{ btn.disabled=false; btn.textContent=old; }
});

// ── 입력 경고 모달: 무엇이 / 왜 / 어떻게 확인할지. 확인 체크를 받아야 계속
function askWarnings(items){
  return new Promise(resolve=>{
    const m=document.getElementById('warnModal'); const list=document.getElementById('warnList'); const ack=document.getElementById('warnAck'); const go=document.getElementById('warnGo');
    list.innerHTML=items.map(w=>`<li><b>${esc(w.what)}</b><span class="why">${esc(w.why)}</span><span class="how">확인: ${esc(w.how)}</span></li>`).join('');
    ack.checked=false; go.disabled=true; m.hidden=false;
    const done=v=>{ m.hidden=true; ack.onchange=go.onclick=document.getElementById('warnBack').onclick=null; resolve(v); };
    ack.onchange=()=>{ go.disabled=!ack.checked; };
    go.onclick=()=>done(true); document.getElementById('warnBack').onclick=()=>done(false);
  });
}

// ── 성적서번호 자동 채번 · 중복 경고 · 발행자 기억
(function(){
  const noEl=document.querySelector('[name="report_no"]'), msg=document.getElementById('dupMsg'), auto=document.getElementById('autoNo');
  const issEl=document.querySelector('[name="issuer"]'); try{ if(issEl&&!issEl.value) issEl.value=localStorage.getItem('issuer')||''; }catch(e){}
  async function suggest(force){ if(!noEl||(noEl.value.trim()&&!force&&noEl.dataset.auto!=='1')) return;
    try{ const r=await (await fetch('/성적서/번호')).json(); noEl.value=r.suggest; noEl.dataset.auto='1'; check(); }catch(e){} }
  async function check(){ if(!noEl||!msg) return; const no=noEl.value.trim(); if(!no){ msg.hidden=true; return; }
    try{ const r=await (await fetch('/성적서/번호확인?no='+encodeURIComponent(no))).json();
      const rb=document.getElementById('reissueBox'); if(rb) rb.hidden=!r.exists;
      if(r.exists){ msg.hidden=false; msg.className='dupmsg'; msg.textContent=`이미 쓴 번호입니다 (${r.n}판 · 마지막 ${r.last}). 그대로 만들면 «수정 재발행» ${r.n+1}판으로 기록됩니다 — 아래에서 사유를 고르세요.`; }
      else if(!r.valid){ msg.hidden=false; msg.className='dupmsg'; msg.textContent=`번호 형식이 다릅니다 (예: ${r.suggest}). 그래도 만들 수는 있습니다.`; }
      else { msg.hidden=false; msg.className='dupmsg ok'; msg.textContent='쓸 수 있는 번호입니다.'; } }catch(e){} }
  if(auto) auto.addEventListener('click',e=>{ e.preventDefault(); suggest(true); });
  if(noEl){ noEl.addEventListener('input',()=>{ noEl.dataset.auto='0'; }); noEl.addEventListener('blur',check); }
  const step2=document.getElementById('step2');
  if(step2) new MutationObserver(()=>{ if(!step2.hidden) suggest(false); }).observe(step2,{attributes:true,attributeFilter:['hidden']});
})();
</script>
<div id="warnModal" class="wmodal" hidden><div class="wbox">
  <div class="wh"><span class="eyebrow">생성 전 입력 점검</span><h3>확인이 필요한 입력이 있습니다</h3>
    <p>아래 항목은 입력이 잘못됐을 때 자주 보이는 모양입니다. 맞게 넣은 것이면 확인하고 계속하세요. 확인하고 만든 성적서는 실적 기록에 «경고 있음» 으로 남습니다.</p></div>
  <ul id="warnList"></ul>
  <label class="wack"><input type="checkbox" id="warnAck"> 위 내용을 확인했습니다. 입력이 맞으니 그대로 만듭니다.</label>
  <div class="wbtn"><button type="button" id="warnBack" class="ghost">돌아가서 고치기</button><button type="button" id="warnGo" disabled>확인하고 생성</button></div>
</div></div>
</body>
</html>
"""

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_radon_empty.xlsx")
TEMPLATE_M = os.path.join(HERE, "template_radon_material.xlsx")
TEMPLATE_K = os.path.join(HERE, "template_kc.xlsx")
TEMPLATE_S = os.path.join(HERE, "template_ks.xlsx")
CODE_FILES = [os.path.join(HERE, f) for f in
              ("server.py", "core.py", "material.py", "kc.py", "sheet.py", "xlsxgrid.py")]

# 성적서 종류. 화면에서 고르면 그에 맞는 입력칸과 계산이 붙는다.
KINDS = {
    "finished": {"mod": core, "template": TEMPLATE,
                 "name": "완제품 (라돈 · 토론)",
                 "files": (("rad7", "RAD7"), ("rd200", "RD200"), ("frd", "FRD400 배경"))},
    "material": {"mod": material, "template": TEMPLATE_M,
                 "name": "원자재 (라돈)",
                 "files": (("frd", "FRD400 배경"), ("eye", "RadonEye Plus"))},
    # KC 는 시험기 CSV 한 개로 성적서 한 장. 계산·채우기는 kc.py, 생성은 generate_kc.
    "ks": {"mod": ks, "template": TEMPLATE_S,
           "name": "매트리스 (KS 규격)",
           "files": (("csv", "내구시험 CSV"),)},
    "kc": {"mod": kc, "template": TEMPLATE_K,
           "name": "매트리스 (KC 안전기준)",
           "files": (("csv", "내구시험 CSV"),)},
}


# 판 번호. 성적서 종류가 늘거나 화면이 크게 바뀌면 가운데 자리를 올린다.
#   1.0  라돈·토론 완제품 자동 작성
#   1.1  사진 편집기 (다듬기 · 비율 · 시료 사진으로 바로 넣기)
#   1.2  라돈 원자재 성적서 · 성적서 고르는 첫 화면
#   1.2.1  붉은 꼬리말 위 가로 구분선이 빠지던 것을 고침 (두 성적서 모두)
#   1.3  테두리 상자를 종이 아래까지 · 사진에 표시하기(도형 그리기)
#   1.3.1  1면에도 바깥 테두리 · 아래 막대를 페이지 머리 막대와 같은 것으로
#   1.3.2  1면 서명·직인 블록을 시료 수와 상관없이 늘 같은 자리에
#   1.4  토론 측정치를 RAD7 DATA No.5~7 세 줄 평균으로 (측정실 규칙)
#   1.4.1  토론 측정치도 라돈처럼 정수로 반올림 (6.73 -> 7)
#   1.5  KC 매트리스 내구시험 성적서 (시험기 CSV 한 개 → 성적서 · 검사 사진 5줄)
#   1.6  KS 매트리스 성적서 (KS G 4300 · 같은 CSV → 3쪽 양식 · 치수 자동 판정 · 사진 8묶음)
#   1.7  발행 기록 · 실적 화면(/실적: 일·주·월·분기·연 묶음, 건수·절감 시간) · 연습용 표시
#   1.8  포털 틀 — 첫 화면은 메뉴(/), 성적서 자동화는 /성적서, 공통 위 막대(portal.py)
#   1.9  경쟁사 뉴스 클리핑 (/뉴스) — 네이버 뉴스 검색, 평일 8시 자동 수집, ★·메모·숨기기
#   1.10 R&D 동향 (/동향) — 신제품 보드 · 규격·인증 감시(법제처·국표원) · 특허 동향(KIPRIS)
#   1.11 경쟁사 제품 현황 (/제품) — 홈페이지 제품 목록을 매일 비교 (시몬스·에이스·씰리·템퍼·지누스·에몬스)
#   1.12 운영 보강 — 자동 다시 읽기 끔 · 갱신은 뒤에서 · 뉴스 90일 보관 · 열쇠 저장 비밀번호 · 에몬스 모델 묶기 ·
#        홈페이지 신제품을 동향 보드에 · 재등록은 신제품으로 안 침 · 로그인 자동 시작(서버시작.bat)
#   1.12.1 뉴스 스팸 차단 — 도박·코인 낱말, 스팸 매체 자동 차단, 제목에 회사 이름·침대 말 필수
#   1.13 임원용 보기 — 첫 화면 «오늘의 브리핑» 보고판, 뉴스 브리핑 보기, 동향·제품 요약 띠
#   1.14 같은 기사 묶기 · 주간 보고서 PDF(/보고서) · 가격대 비교·가격 이력 · 전시회 일정(/일정) · 특허 IPC 분포 · 규격 요약집(/규격)
#   1.15 열쇠 .env 분리 · 일정 확정 · 실적: 소급 등록 · 기준 시간 확정 근거 · 자동 채번 · 발행 이력/판 보관 · 계산 검증 탭
#   1.16 성적서 생성 전 입력 이상치 점검(배경농도·기기 차이·온습도·날짜·사진·치수 판정) — 점검설정.json
#   1.17 실적 «임원 보고용 한 장» — KPI 5 · 신뢰성 뱃지 · 실측 기반 기준 시간(확정/확인 중) · 수정 재발행·품질 기록 · 전망선 · 엑셀 · ?demo=1
VERSION = "1.17.0"


def _stamp_now():
    try:
        t = max(os.path.getmtime(p) for p in CODE_FILES if os.path.exists(p))
        return datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
    except Exception:
        return "-"


# 지금 '실행 중인' 코드가 언제 것인지. 모듈을 읽어들인 순간에 한 번만 재어 둔다.
# 요청 때마다 파일 시각을 다시 읽으면, 코드가 바뀌었는데 서버가 옛것을 돌리는
# 상황에서도 최신 시각을 보여줘 거짓말을 하게 된다.
BUILD = _stamp_now()

# 사진칸의 가로세로 비율. 편집기의 자르기 틀이 이 모양이라야
# 사용자가 고른 자리가 성적서에 그대로 들어간다.
try:
    PHOTO_ASPECT = core.photo_box_aspect(TEMPLATE)
except Exception:
    PHOTO_ASPECT = 2.076
try:
    PHOTO_ASPECT_M = material.photo_box_aspect(TEMPLATE_M)
except Exception:
    PHOTO_ASPECT_M = 1.3779
try:
    PHOTO_ASPECT_K = kc.photo_box_aspect(TEMPLATE_K)
    PHOTO_ASPECT_S = ks.photo_box_aspect(TEMPLATE_S)
except Exception:
    PHOTO_ASPECT_K = 1.11


def build_stamp():
    """화면에 표시할 버전. 파일이 더 새것이면 그것도 같이 알려준다.

    코드를 고쳐놓고 옛 서버가 그대로 돌고 있으면 화면만 보고는 알 수 없다.
    그래서 켤 때 잰 시각과 지금 파일 시각을 견줘 다르면 짚어준다.
    """
    now = _stamp_now()
    if now != BUILD:
        return "v%s · %s  (파일은 %s — 서버를 다시 켜세요)" % (VERSION, BUILD, now)
    return "v%s · %s" % (VERSION, BUILD)


@app.route("/")
def home():
    return portal.home(build_stamp())


@app.route("/홈/data")
def home_data():
    return jsonify(portal.brief())


@app.route("/성적서")
def index():
    return render_template_string(PAGE, today=date.today().strftime("%Y년 %m월 %d일"),
                                  nav=portal.nav("/성적서", "", build_stamp()),
                                  nav_css=portal.NAV_CSS,
                                  max_samples=core.MAX_SAMPLES, max_runs=core.MAX_RUNS,
                                  max_runs_m=material.MAX_RUNS,
                                  photo_aspect=PHOTO_ASPECT, photo_aspect_m=PHOTO_ASPECT_M,
                                  photo_aspect_k=PHOTO_ASPECT_K,
                                  kc_photo_rows=[(r, kc.PHOTO_ROW_NAMES[r]) for r in kc.L.PHOTO_ROWS],
                                  kc_last_choices=kc.LAST_CHOICES,
                                  photo_aspect_s=PHOTO_ASPECT_S,
                                  ks_photo_rows=[(r, ks.PHOTO_ROW_NAMES[r]) for r in ks.PHOTO_ROWS],
                                  ks_judges=ks.JUDGE_ITEMS, ks_groups=ks.GROUP_NAMES,
                                  ks_dim_default=ks.DIM_DEFAULT,
                                  photo_roi=list(core.PHOTO_ROI),
                                  build=build_stamp())


def _mark_practice(form, header):
    """«연습용» 으로 만들면 성적서번호 칸에 그 말을 찍어 실제 성적서와 섞이지 않게 한다."""
    if form.get("practice") == "1":
        header["report_no"] = ("연습용 " + (header.get("report_no") or "")).strip()


def _log_issue(kind, form, n_samples, n_runs, n_photos, resp, t0, blob=None):
    """성적서를 만들 때마다 발행기록.jsonl 에 한 줄을 남기고 만든 파일의 사본을 발행/ 폴더에 둔다.
    같은 번호를 다시 만들면 판(version)이 올라가고 이전 판 파일은 그대로 남는다. 기록이 실패해도 성적서는 나간다."""
    try:
        report_no = (form.get("report_no") or "").strip()
        practice = form.get("practice") == "1"
        prev = stats.same_no(report_no) if (report_no and not practice) else []
        version = len(prev) + 1
        out_rel = ""
        if blob is not None and not practice:
            path = stats.archive_path(report_no, version)
            with open(path, "wb") as fh:
                fh.write(blob)
            out_rel = os.path.relpath(path, HERE)
        src = [f.filename for k, f in request.files.items() if f and f.filename and not k.startswith(("kphoto_", "sphoto_", "photo_"))]
        backdated = form.get("backdated") == "1"
        issued_on = stats.parse_issue_date(form.get("issue_date", "")) if backdated else None
        host = request.remote_addr or ""
        try:
            import socket
            host = socket.gethostbyaddr(request.remote_addr)[0] if request.remote_addr not in ("127.0.0.1", "::1") else "이 PC"
        except Exception:
            pass
        try:
            warn_items = json.loads(form.get("warn_items") or "[]")
            warn_items = [str(x)[:160] for x in warn_items][:12]
        except Exception:
            warn_items = []
        stats.record(kind, {"report_no": report_no, "sample_title": form.get("sample_title", "")},
                     n_samples=n_samples, n_runs=n_runs, n_photos=n_photos,
                     warnings=1 if (resp.headers.get("X-Report-Warning") or warn_items) else 0,
                     warn_items=warn_items, acked=form.get("ack_warnings") == "1",
                     elapsed=time.time() - t0, practice=practice, ip=request.remote_addr or "",
                     issuer=form.get("issuer", ""), host=host, src_files=src, out_file=out_rel,
                     version=version, backdated=backdated, issued_on=issued_on,
                     reissue_reason=form.get("reissue_reason", ""))
        if prev:
            w = resp.headers.get("X-Report-Warning", "")
            resp.headers["X-Report-Warning"] = (w + " " if w else "") + quote("같은 성적서번호 %d판째입니다. 이전 판은 서버에 보관됩니다." % version)
        if backdated and not issued_on:
            w = resp.headers.get("X-Report-Warning", "")
            resp.headers["X-Report-Warning"] = (w + " " if w else "") + quote("소급 등록인데 발급일자를 날짜로 읽지 못해 오늘 날짜로 집계했습니다.")
    except Exception:
        app.logger.exception("발행 기록 실패")


@app.route("/뉴스")
def news_page():
    return news.page(build_stamp())


@app.route("/뉴스/data")
def news_data():
    a = request.args
    try:
        days = max(1, min(int(a.get("days", 7)), 365))
    except ValueError:
        days = 7
    return jsonify(news.query(days=days, group=a.get("group", ""), company=a.get("company", ""),
                              tag=a.get("tag", ""), star_only=a.get("star") == "1", q=a.get("q", "")))


def _bg(fn):
    """긴 수집은 뒤에서 돌리고 바로 돌아간다. 화면은 busy 가 꺼질 때까지 몇 초마다 다시 읽는다."""
    import threading
    threading.Thread(target=fn, daemon=True).start()


@app.route("/뉴스/수집", methods=["POST"])
def news_collect():
    if news._running["busy"]:
        return jsonify(ok=False, busy=True)
    _bg(lambda: news.run_now())
    return jsonify(ok=True, started=True)


@app.route("/뉴스/표시", methods=["POST"])
def news_mark():
    j = request.get_json(force=True) or {}
    if not j.get("key"):
        return jsonify(ok=False), 400
    return jsonify(ok=True, mark=news.set_mark(j["key"], j.get("star"), j.get("memo"), j.get("hide")))


@app.route("/뉴스/설정", methods=["POST"])
def news_settings():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    news.save_settings(request.get_json(force=True) or {})
    return jsonify(ok=True, has_key=news.has_naver_key(), source=news.active_source())


@app.route("/동향")
def trend_page():
    return trend.page(build_stamp())


@app.route("/동향/data")
def trend_data():
    return jsonify(trend.data())


@app.route("/동향/수집", methods=["POST"])
def trend_collect():
    if trend._busy["on"]:
        return jsonify(ok=False, busy=True)
    _bg(lambda: trend.collect_safe(app.logger))
    return jsonify(ok=True, started=True)


@app.route("/동향/표시", methods=["POST"])
def trend_mark():
    j = request.get_json(force=True) or {}
    if not j.get("key"):
        return jsonify(ok=False), 400
    return jsonify(ok=True, mark=trend.set_mark(j["key"], j.get("star"), j.get("memo"), j.get("hide")))


@app.route("/동향/특허설정", methods=["POST"])
def trend_pat_settings():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    trend.save_pat_settings(request.get_json(force=True) or {})
    return jsonify(ok=True, has_key=trend.has_pat_key())


# ─── 주간 보고서
@app.route("/보고서")
def report_page():
    return report.page(build_stamp())


@app.route("/보고서/data")
def report_data():
    return jsonify(report.data())


@app.route("/보고서/미리보기")
def report_preview():
    from datetime import date as _d
    try:
        a, b = _d.fromisoformat(request.args.get("from", "")), _d.fromisoformat(request.args.get("to", ""))
    except ValueError:
        a, b = report.last_week()
    if b < a:
        a, b = b, a
    return report.render(report.gather(a, b))


@app.route("/보고서/생성", methods=["POST"])
def report_make():
    from datetime import date as _d
    j = request.get_json(force=True) or {}
    try:
        a, b = _d.fromisoformat(j.get("from", "")), _d.fromisoformat(j.get("to", ""))
    except ValueError:
        return jsonify(ok=False, error="날짜가 틀립니다"), 400
    if b < a:
        a, b = b, a
    if (b - a).days > 92:
        return jsonify(ok=False, error="한 번에 석 달까지만 만듭니다"), 400
    if not report.make_async(a, b):
        return jsonify(ok=False, busy=True, error="이미 만드는 중입니다")
    return jsonify(ok=True, started=True)


@app.route("/보고서/파일/<name>")
def report_file(name):
    if not re.match(r"주간보고_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.pdf$", name):
        abort(404)
    return send_from_directory(report.DIR, name, mimetype="application/pdf", as_attachment=True)


# ─── 전시회·학회 일정
@app.route("/일정")
def events_page():
    return events.page(build_stamp())


@app.route("/일정/data")
def events_data():
    return jsonify(events.data())


@app.route("/일정/저장", methods=["POST"])
def events_save():
    try:
        return jsonify(ok=True, id=events.save(request.get_json(force=True) or {}))
    except ValueError as e:
        return jsonify(ok=False, error="날짜나 이름이 틀립니다: %s" % e), 400


@app.route("/일정/확인", methods=["POST"])
def events_confirm():
    events.confirm((request.get_json(force=True) or {}).get("id", ""))
    return jsonify(ok=True)


@app.route("/일정/삭제", methods=["POST"])
def events_delete():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    events.delete((request.get_json(force=True) or {}).get("id", ""))
    return jsonify(ok=True)


# ─── 인증 현황
@app.route("/인증")
def certs_page():
    return certs.page(build_stamp())


@app.route("/인증/data")
def certs_data():
    return jsonify(certs.data())


@app.route("/인증/저장", methods=["POST"])
def certs_save():
    try:
        return jsonify(ok=True, id=certs.save_cert(request.get_json(force=True) or {}))
    except ValueError as e:
        return jsonify(ok=False, error="입력이 틀립니다: %s" % e), 400


@app.route("/인증/삭제", methods=["POST"])
def certs_delete():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    certs.delete_cert((request.get_json(force=True) or {}).get("id", ""))
    return jsonify(ok=True)


@app.route("/인증/확인", methods=["POST"])
def certs_clear_check():
    j = request.get_json(force=True) or {}
    certs.clear_check(j.get("kind", "cert"), j.get("id", ""))
    return jsonify(ok=True)


@app.route("/인증/제품저장", methods=["POST"])
def certs_product_save():
    try:
        return jsonify(ok=True, id=certs.save_product(request.get_json(force=True) or {}))
    except ValueError as e:
        return jsonify(ok=False, error="입력이 틀립니다: %s" % e), 400


@app.route("/인증/제품삭제", methods=["POST"])
def certs_product_delete():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    certs.delete_product((request.get_json(force=True) or {}).get("id", ""))
    return jsonify(ok=True)


@app.route("/인증/설정", methods=["POST"])
def certs_settings():
    return jsonify(ok=True, settings=certs.save_settings(request.get_json(force=True) or {}))


@app.route("/인증/가져오기", methods=["POST"])
def certs_import():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".xlsx"):
        return jsonify(ok=False, error=".xlsx 파일을 올려 주세요"), 400
    try:
        r = certs.import_xlsx(io.BytesIO(f.read()))
        r["ok"] = True
        return jsonify(r)
    except Exception as e:
        app.logger.exception("인증 엑셀 가져오기 실패")
        return jsonify(ok=False, error="읽지 못했습니다: %s" % e), 400


@app.route("/인증/내보내기")
def certs_export():
    buf, name = certs.export_xlsx()
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ─── 시험 규격 요약집
@app.route("/규격")
def standards_page():
    return standards.page(build_stamp())


@app.route("/규격/data")
def standards_data():
    return jsonify(standards.data())


@app.route("/규격/저장", methods=["POST"])
def standards_save():
    if not portal.admin_ok(request):
        return jsonify(ok=False, error="관리 비밀번호가 틀립니다"), 403
    j = request.get_json(force=True) or {}
    standards.save_note(j.get("id", ""), j.get("note", ""), j.get("extra", []))
    return jsonify(ok=True)


@app.route("/제품")
def products_page():
    return products.page(build_stamp())


@app.route("/제품/data")
def products_data():
    try:
        days = max(1, min(int(request.args.get("days", 30)), 365))
    except ValueError:
        days = 30
    return jsonify(products.data(days))


@app.route("/제품/이력")
def products_history():
    company, pid, link = request.args.get("company", ""), request.args.get("id", ""), request.args.get("link", "")
    if not pid and link:          # 옛 화면에서 링크만 온 경우
        snap = products._load_snap().get(company, {}).get("items", {})
        pid = next((k for k, v in snap.items() if v.get("link") == link), "")
    return jsonify(products.history(company, pid))


@app.route("/제품/수집", methods=["POST"])
def products_collect():
    if products._busy["on"]:
        return jsonify(ok=False, busy=True)
    _bg(lambda: products.collect_safe(app.logger))
    return jsonify(ok=True, started=True)


@app.route("/실적")
def stats_page():
    return stats.page(build_stamp())


@app.route("/실적/data")
def stats_data():
    return jsonify(stats.data_for(request.args))


@app.route("/실적/설정값")
def stats_settings_values():
    s = stats.settings()
    s.pop("excluded", None)
    return jsonify(s)


@app.route("/실적/사유", methods=["POST"])
def stats_reason():
    j = request.get_json(force=True) or {}
    return jsonify(ok=stats.set_reason(int(j.get("id", 0)), j.get("reason", "")))


@app.route("/실적/엑셀")
def stats_xlsx():
    if request.args.get("demo") == "1":
        rows, s = stats.demo_rows()
    else:
        rows, s = stats.load(), stats.settings()
    buf = stats.export_xlsx(rows, s)
    name = "성적서_발행기록_%s%s.xlsx" % (date.today().isoformat(), "_데모" if request.args.get("demo") == "1" else "")
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/성적서/점검", methods=["POST"])
def report_precheck():
    """생성 전에 같은 양식 데이터를 받아 이상치만 돌려준다. 파일은 저장하지 않는다."""
    kind = request.form.get("kind", "finished")
    if kind not in KINDS:
        kind = "finished"
    try:
        items = precheck.run(request.form, request.files, kind)
    except Exception as e:
        app.logger.exception("입력 점검 실패")
        items = [precheck.W("입력 점검을 끝내지 못했습니다", "%s" % type(e).__name__, "그대로 만들어도 되지만 결과를 한 번 더 보세요")]
    return jsonify(ok=True, warnings=items)


@app.route("/성적서/번호")
def report_next_no():
    no, prefix = stats.next_number(request.args.get("kind"))
    return jsonify(suggest=no, prefix=prefix)


@app.route("/성적서/번호확인")
def report_check_no():
    no = (request.args.get("no") or "").strip()
    prev = stats.same_no(no)
    sug, _ = stats.next_number()
    return jsonify(exists=bool(prev), n=len(prev), last=(prev[-1]["ts"][:16].replace("T", " ") if prev else ""),
                   valid=bool(stats.NO_RE.match(no)), suggest=sug)


@app.route("/실적/파일/<int:rec_id>")
def stats_file(rec_id):
    r = next((x for x in stats.load() if int(x["id"]) == rec_id), None)
    if not r or not r.get("out_file"):
        abort(404)
    path = os.path.join(HERE, r["out_file"])
    if not os.path.exists(path):
        abort(404)
    name = "%s_v%d.xlsx" % (_safe_name(r.get("report_no") or r.get("sample_title") or "성적서"), r.get("version", 1))
    return send_file(path, as_attachment=True, download_name=name)


@app.route("/실적/검증", methods=["GET", "POST"])
def stats_verify():
    if request.method == "POST":
        return jsonify(ok=verify.run_async())
    return jsonify(verify.result())


@app.route("/실적/설정", methods=["GET", "POST"])
def stats_settings():
    if request.method == "GET":
        return stats.settings_page(build_stamp())
    j = request.get_json(force=True) or {}
    return jsonify(ok=True, settings=stats.save_settings(j, by=j.get("by", "")))


@app.route("/실적/제외", methods=["POST"])
def stats_exclude():
    j = request.get_json(force=True) or {}
    stats.set_excluded(int(j.get("id", 0)), bool(j.get("excluded")))
    return jsonify(ok=True)


def _safe_name(s):
    """내려받는 파일 이름에 못 쓰는 글자(역슬래시 / : * ? " < > |)를 밑줄로."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(s)).strip(" ._")
    return s[:80] or "성적서"


def generate_kc(form, tmp):
    """KC 내구시험 — CSV 한 개, 사진은 줄(45·46·53·54·55행)마다 최대 3장."""
    header = {k: form.get(k, "").strip() for k in
              ("report_no", "sample_title", "purpose", "request_date", "issue_date",
               "place", "temp", "humid", "test_date", "fabric")}
    _mark_practice(form, header)
    header["dims"] = tuple(form.get(k, "").strip() for k in ("dim_w", "dim_l", "dim_t"))
    header["judge"] = {k: (form.get("judge_" + k) if form.get("judge_" + k) in ks.VERDICTS else "적합")
                       for k in ("appearance", "dims", "material", "durability", "fabric")}
    header["dims"] = tuple(ks.clean_num(v) for v in header["dims"])
    try:
        last = int(form.get("last_cycle", kc.LAST_CHOICES[0]))
    except ValueError:
        last = kc.LAST_CHOICES[0]

    f = request.files.get("csv_0")
    if not (f and f.filename):
        raise kc.InputError("내구시험기 CSV 파일을 올려주세요.")
    data = kc.parse_upload(kc.read_text(f), f.filename)
    values = kc.compute(data, last)

    photos = {}
    for row in kc.L.PHOTO_ROWS:
        lst = []
        for k in range(3):
            fp = request.files.get("kphoto_%d_%d" % (row, k))
            if not (fp and fp.filename):
                continue
            path = os.path.join(tmp, "kc_%d_%d.jpg" % (row, k))
            try:
                kc.save_photo(fp, path)
            except kc.InputError as e:
                raise kc.InputError("%s 사진 %d: %s" % (kc.PHOTO_ROW_NAMES[row], k + 1, e))
            lst.append({"path": path, "cropped": form.get("kcrop_%d_%d" % (row, k)) == "1"})
        if lst:
            photos[row] = lst

    out = os.path.join(tmp, "report.xlsx")
    warnings = kc.build_report(TEMPLATE_K, header, values, photos, out)
    with open(out, "rb") as fh:
        blob = io.BytesIO(fh.read())
    shutil.rmtree(tmp, ignore_errors=True)
    fname = "KC성적서_%s.xlsx" % _safe_name(header.get("sample_title") or "kc")
    resp = send_file(blob, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet")
    if warnings:
        resp.headers["X-Report-Warning"] = quote(" ".join(warnings))
    return resp, blob.getvalue()


def generate_ks(form, tmp):
    """KS 매트리스 — CSV 한 개, 사진은 묶음(8곳)마다 최대 3장. 치수는 허용차로 자동 판정."""
    header = {k: form.get(k, "").strip() for k in
              ("report_no", "sample_title", "purpose", "request_date", "issue_date",
               "place", "temp", "humid", "test_date")}
    _mark_practice(form, header)
    header["fabric"] = form.get("ks_fabric", "").strip()
    header["dims"] = tuple(form.get(k, "").strip() for k in ("ks_dim_w", "ks_dim_l", "ks_dim_t"))
    header["dim_spec"] = {k: form.get("ks_spec_" + k, "").strip() for k in ("w", "l", "t")}
    header["dims_judge"] = form.get("ks_dims_judge") or "자동"
    header["judge"] = {k: (form.get("ks_judge_" + k) if form.get("ks_judge_" + k) in ks.VERDICTS else "적합")
                       for k, _, _, _ in ks.JUDGE_ITEMS}

    f = request.files.get("csv_0")
    if not (f and f.filename):
        raise ks.InputError("내구시험기 CSV 파일을 올려주세요.")
    data = ks.parse_upload(ks.read_text(f), f.filename)
    values = ks.compute(data)

    photos = {}
    for row in ks.PHOTO_ROWS:
        lst = []
        for k in range(3):
            fp = request.files.get("sphoto_%d_%d" % (row, k))
            if not (fp and fp.filename):
                continue
            path = os.path.join(tmp, "ks_%d_%d.jpg" % (row, k))
            try:
                ks.save_photo(fp, path)
            except ks.InputError as e:
                raise ks.InputError("%s 사진 %d: %s" % (ks.PHOTO_ROW_NAMES[row], k + 1, e))
            lst.append({"path": path, "cropped": form.get("scrop_%d_%d" % (row, k)) == "1"})
        if lst:
            photos[row] = lst

    out = os.path.join(tmp, "report.xlsx")
    warnings = ks.build_report(TEMPLATE_S, header, values, photos, out)
    with open(out, "rb") as fh:
        blob = io.BytesIO(fh.read())
    shutil.rmtree(tmp, ignore_errors=True)
    fname = "KS성적서_%s.xlsx" % _safe_name(header.get("sample_title") or "ks")
    resp = send_file(blob, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet")
    if warnings:
        resp.headers["X-Report-Warning"] = quote(" ".join(warnings))
    return resp, blob.getvalue()


@app.route("/generate", methods=["POST"])
def generate():
    tmp = tempfile.mkdtemp()
    try:
        form = request.form
        header = {k: form.get(k, "") for k in
                  ("report_no", "sample_title", "purpose", "request_date", "issue_date",
                   "place", "temp", "humid", "method")}
        kind = form.get("kind", "finished")
        if kind not in KINDS:
            kind = "finished"
        t0 = time.time()
        if kind in ("kc", "ks"):
            resp, data = generate_kc(form, tmp) if kind == "kc" else generate_ks(form, tmp)
            _log_issue(kind, form, n_samples=1, n_runs=1,
                       n_photos=sum(1 for k, f in request.files.items()
                                    if k.startswith(("kphoto_", "sphoto_")) and f.filename),
                       resp=resp, t0=t0, blob=data)
            return resp
        _mark_practice(form, header)
        spec = KINDS[kind]
        mod = spec["mod"]
        try:
            n_runs = max(1, min(int(form.get("n_runs", 1)), mod.MAX_RUNS))
        except ValueError:
            n_runs = 1

        batches, periods = [], []
        for ri in range(n_runs):
            tag = "%d번째 측정" % (ri + 1)
            got = {}
            miss = []
            for key, lab in spec["files"]:
                f = request.files.get("%s_%d" % (key, ri))
                if f and f.filename:
                    got[key] = f
                else:
                    miss.append(lab)
            if miss:
                raise mod.InputError("%s: %s 파일을 올려주세요." % (tag, " · ".join(miss)))

            names = form.getlist("sname_%d[]" % ri)
            sizes = form.getlist("ssize_%d[]" % ri)
            sizes += [""] * (len(names) - len(sizes))
            samples = [(n.strip(), s.strip()) for n, s in zip(names, sizes) if n.strip()]
            if not samples:
                raise mod.InputError("%s: 시료 이름을 최소 1개 입력해주세요." % tag)

            try:
                if kind == "material":
                    BG = mod.parse_upload(mod.read_text(got["frd"]),
                                          got["frd"].filename, "FRD400")
                    EY = mod.parse_upload(mod.read_text(got["eye"]),
                                          got["eye"].filename, "EYE")
                    v = mod.compute(BG, EY)
                else:
                    R7 = mod.parse_upload(mod.read_text(got["rad7"]),
                                          got["rad7"].filename, "RAD7")
                    RD = mod.parse_upload(mod.read_text(got["rd200"]),
                                          got["rd200"].filename, "RD200")
                    BG = mod.parse_upload(mod.read_text(got["frd"]),
                                          got["frd"].filename, "FRD400")
                    v = mod.compute(R7, RD, BG)
            except mod.InputError as e:
                raise mod.InputError("%s: %s" % (tag, e))
            periods.append(v["period"])

            photo = None
            fp = request.files.get("photo_%d" % ri)
            if fp and fp.filename:
                photo = os.path.join(tmp, "p%d.jpg" % ri)
                try:
                    mod.save_photo(fp, photo)
                except mod.InputError as e:
                    raise mod.InputError("%s 사진: %s" % (tag, e))
            # 사용자가 화면에서 직접 잘라 보낸 사진은 이미 사진칸 비율에 맞다.
            # 다시 손대면 애써 고른 자리가 어긋나므로 그대로 쓴다.
            cropped = bool(photo) and form.get("crop_%d" % ri) == "1"
            batches.append({"values": v, "samples": samples, "photo": photo,
                            "cropped": cropped, "caption": None})

        if periods:
            header["test_date"] = "%s ~ %s" % (periods[0][0][:10], periods[-1][1][:10])

        out = os.path.join(tmp, "report.xlsx")
        warnings = mod.build_report(spec["template"], header, batches, out)

        # 윈도우에서는 열려 있는 파일을 지울 수 없어, 메모리로 옮긴 뒤 임시폴더를 정리한다
        with open(out, "rb") as fh:
            blob = io.BytesIO(fh.read())
        shutil.rmtree(tmp, ignore_errors=True)

        fname = "성적서_%s.xlsx" % _safe_name(header.get("sample_title") or "radon")
        resp = send_file(blob, as_attachment=True, download_name=fname,
                         mimetype="application/vnd.openxmlformats-officedocument."
                                  "spreadsheetml.sheet")
        if warnings:
            resp.headers["X-Report-Warning"] = quote(" ".join(warnings))
        _log_issue(kind, form, n_samples=sum(len(b["samples"]) for b in batches),
                   n_runs=len(batches), n_photos=sum(1 for b in batches if b["photo"]),
                   resp=resp, t0=t0, blob=blob.getvalue())
        return resp

    except core.InputError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        app.logger.exception("성적서 생성 실패")
        return jsonify(ok=False, error="생성 중 오류가 발생했습니다. (%s: %s)"
                       % (type(e).__name__, e)), 500


def port_busy(port=5000):
    """이미 다른 서버가 그 포트를 쓰고 있는지."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


if __name__ == "__main__":
    import webbrowser, threading, sys

    first = os.environ.get("WERKZEUG_RUN_MAIN") != "true"

    # 서버가 겹쳐 뜨면 옛 코드가 계속 응답해서 결과가 이상해진다.
    if first and port_busy():
        print("")
        print("  [중단] 이미 다른 서버가 5000 포트를 쓰고 있습니다.")
        print("")
        print("  그대로 두면 옛 코드가 응답해서 성적서가 이상하게 나옵니다.")
        print("  먼저 그 창에서 Ctrl+C 로 끄고 다시 실행하세요.")
        print("")
        print("  창을 못 찾겠으면 명령창에 이걸 붙여넣어 전부 끄세요:")
        print("    taskkill /F /IM python.exe")
        print("")
        sys.exit(1)
    if first and os.environ.get("RNDHUB_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()

    if first:
        print("")
        print("  사내 시험 성적서 자동 작성")
        print("  프로그램 판 %s" % build_stamp())
        print("  주소  http://127.0.0.1:5000   (팀원은 http://<이 PC의 사내IP>:5000)")
        print("  종료  Ctrl+C")
        print("")
        print("  * 코드를 고친 뒤에는 이 창을 닫고 서버시작.bat 으로 다시 켜세요.")
        print("    (저장 도중 반쯤 쓰인 파일을 읽다 서버가 죽는 일이 있어 자동 다시 읽기는 껐습니다)")
        print("")

    # 수집 스케줄러 (평일 8시): 뉴스 → R&D 동향 → 경쟁사 제품 현황 순서로
    news.AFTER_COLLECT.append(lambda: trend.collect_safe(app.logger))
    news.AFTER_COLLECT.append(lambda: products.collect_safe(app.logger))
    news.AFTER_COLLECT.append(lambda: report.weekly_if_due(app.logger))   # 월요일이면 지난주 보고서 PDF
    news.start_scheduler(app.logger)

    # use_reloader=False: 코드를 고치면 서버를 직접 다시 켠다. 화면 왼쪽 아래 판 시각 옆에
    # «서버를 다시 켜세요» 가 뜨면 파일이 실행 중인 코드보다 새 것이다.
    # (debug=False 이므로 오류 화면에 코드가 노출되지 않는다)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
