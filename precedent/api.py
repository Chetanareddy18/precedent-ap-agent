"""FastAPI server: JSON API for the AP workbench + the static single-page UI.

    uvicorn precedent.api:app --reload
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import APAgent
from .config import ROOT, settings
from .llm import LLM
from .memory import build_memory
from .models import Action, ClerkResolution
from .session import Session, Step

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

memory = build_memory(settings.hindsight_base_url, settings.hindsight_api_key, settings.bank_id)
llm = LLM(settings.llm_api_key, settings.llm_base_url, [settings.llm_model, settings.llm_fallback_model])
agent = APAgent(settings, memory, llm)
session = Session.load(agent)

app = FastAPI(title="Precedent — AP exception agent with Hindsight memory")


@app.on_event("startup")
async def fresh_bank():
    """Every server start is a new 12-week replay, so it gets an empty memory bank."""
    await memory.reset()


def _step_view(step: Step | None) -> dict[str, Any] | None:
    if step is None:
        return None
    inv, v = step.invoice, agent.vendors[step.invoice.vendor_id]
    return {
        "invoice": {**inv.model_dump(mode="json"), "subtotal": inv.subtotal, "tax": inv.tax, "total": inv.total,
                    "total_inr": inv.total_inr},
        "vendor": v.model_dump(mode="json"),
        "po": agent.pos[inv.po_number].model_dump(mode="json") if inv.po_number in agent.pos else None,
        "grn": agent.grns[inv.po_number].model_dump(mode="json") if inv.po_number in agent.grns else None,
        "decision": step.decision.model_dump(mode="json"),
        "payable_options": agent.payable_options(inv, step.decision.charge_cap or 3000.0),
        "grade": step.grade, "final_action": step.final_action, "final_payable": step.final_payable,
        "retained": step.retained,
    }


def _state() -> dict[str, Any]:
    done = {s.invoice.invoice_id: s for s in session.steps}
    queue = []
    for inv in session.invoices:
        s = done.get(inv.invoice_id)
        queue.append({"invoice_id": inv.invoice_id, "invoice_number": inv.invoice_number,
                      "vendor": agent.vendors[inv.vendor_id].name, "vendor_id": inv.vendor_id,
                      "date": inv.received_on.isoformat(), "total_inr": inv.total_inr,
                      "status": s.grade if s else ("pending" if session.pending and
                                                   session.pending.invoice.invoice_id == inv.invoice_id else "queued"),
                      "route": s.decision.route.value if s else None,
                      "final_action": s.final_action if s else None})
    return {
        "memory_backend": memory.backend, "bank_id": getattr(memory, "bank_id", settings.bank_id), "llm": llm.label,
        "use_memory": session.use_memory, "queue": queue, "metrics": session.metrics(),
        "timeline": session.timeline(), "pending": _step_view(session.pending), "feed": session.feed[:12],
        "current": _step_view(session.pending or (session.steps[-1] if session.steps else None)),
        "done": session.done,
    }


@app.get("/api/steps/{invoice_id}")
async def step_detail(invoice_id: str):
    for s in session.steps:
        if s.invoice.invoice_id == invoice_id:
            return _step_view(s)
    if session.pending and session.pending.invoice.invoice_id == invoice_id:
        return _step_view(session.pending)
    raise HTTPException(404, "Not processed yet")


class ResetBody(BaseModel):
    use_memory: bool = True
    wipe_memory: bool = True


class ResolveBody(BaseModel):
    accept: bool = False
    action: Action | None = None
    basis: str | None = None
    charge_cap: float | None = None
    note: str = ""
    make_policy: bool = False


class AskBody(BaseModel):
    question: str
    vendor_id: str | None = None


@app.get("/api/state")
async def state():
    return _state()


@app.post("/api/reset")
async def reset(body: ResetBody):
    global session
    async with session.lock:
        if body.wipe_memory:
            await memory.reset()
        agent.history.clear()
        session = Session.load(agent, use_memory=body.use_memory)
    return _state()


@app.post("/api/next")
async def next_invoice():
    async with session.lock:
        await session.next()
    return _state()


@app.post("/api/resolve")
async def resolve(body: ResolveBody):
    async with session.lock:
        if session.pending is None:
            raise HTTPException(409, "No invoice is waiting for a decision")
        try:
            if body.accept:
                await session.resolve(None)
            else:
                if body.action is None:
                    raise HTTPException(422, "action is required unless accept=true")
                res = ClerkResolution(invoice_id=session.pending.invoice.invoice_id, action=body.action,
                                      note=body.note.strip(), make_policy=body.make_policy)
                await session.resolve(res, basis=body.basis, charge_cap=body.charge_cap)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return _state()


@app.post("/api/autopilot")
async def autopilot():
    """One step of the clerk simulator (replays the AP lead's recorded decisions)."""
    step = await session.autopilot_step()
    return {"step": _step_view(step), "state": _state()}


@app.post("/api/compare")
async def compare():
    """Re-run the pending invoice with memory OFF, to show the stateless answer side by side."""
    if session.pending is None:
        raise HTTPException(409, "No pending invoice")
    d = await agent.decide(session.pending.invoice, use_memory=False)
    return d.model_dump(mode="json")


@app.post("/api/ask")
async def ask(body: AskBody):
    if not body.question.strip():
        raise HTTPException(422, "Ask a question")
    try:
        ans = await memory.reflect(body.question.strip(),
                                   tags=[f"vendor:{body.vendor_id}"] if body.vendor_id else None)
    except Exception as exc:
        raise HTTPException(502, f"Hindsight reflect failed: {exc}") from exc
    return {"answer": ans.text, "sources": [s.model_dump() for s in ans.sources]}


@app.get("/api/vendors/{vendor_id}/playbook")
async def playbook(vendor_id: str):
    if vendor_id not in agent.vendors:
        raise HTTPException(404, "unknown vendor")
    return {"vendor": agent.vendors[vendor_id].name, "content": await memory.playbook(vendor_id)}


@app.get("/api/directives")
async def directives():
    return await memory.directives()


WEB = ROOT / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
async def index():
    return FileResponse(Path(WEB) / "index.html")
