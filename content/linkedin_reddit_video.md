# LinkedIn post (Prompt 3) — under 800 characters

Post this text. Then add the ARTICLE URL as the FIRST comment, and the Hindsight repo as a second comment.
Tag Code.in if you used it.

---

My AP agent approved ₹6,800 of freight because it once saw ₹2,400 approved.

It had memory. It remembered the wrong thing.

What fixed it:

→ Retain the clerk's reason, not the outcome. "Approve, clause 7.2, cap ₹3,000" teaches when NOT to approve.
→ Scope recall by owner. vendor:V001 precedents are citable; other vendors are hints only.
→ Before: every exception to a human. After: repeats auto-resolve with a cited precedent; over-cap ones still escalate.
→ The LLM picks a payable basis. Code does the maths.
→ Memory adds autonomy, never removes a control.

Built on Hindsight agent memory: retain, tag-scoped recall, directives, mental models.

Code: https://github.com/Chetanareddy18/precedent-ap-agent

#AIAgents #AgentMemory #Hindsight #LLM

---

**First comment:** Full write-up: <YOUR ARTICLE URL>

**Second comment:** Here's a link to Hindsight if you want to check it out: https://github.com/vectorize-io/hindsight

---

# Reddit (link post)

Subreddit: r/AIAgents (or r/LLMDevs, r/SideProject, r/AIMemory). Choose **Link** post type.

- **Title:** I stored the clerk's reason in Hindsight, not the decision
- **URL:** <YOUR ARTICLE URL>
- **Body (optional):** Built an accounts-payable agent that resolves repeat invoice exceptions by recalling how the AP team resolved them before (Hindsight memory, tag-scoped per vendor). The interesting bit: retaining outcomes made it copy decisions blindly; retaining the reason with its caps/dates made it check conditions. Repo: https://github.com/Chetanareddy18/precedent-ap-agent

---

# Video script (Prompt 5) — ~3 minutes, screen recording + voice

**Setup before recording:** `uvicorn precedent.api:app --port 8000`, open http://localhost:8000, browser zoom 110%,
editor font up, notifications off. Click **Reset** (twice to confirm) so memory is empty.

### 0:00 – 0:30 · Intro (webcam + app on screen)
"Hi, I'm Chetana. This is Precedent, an accounts-payable agent that resolves invoice exceptions the way your team
resolved them last time. AP clerks spend hours on exceptions that are really reruns, the same vendor doing the same
thing, and the knowledge to fix them lives in one senior person's head."

### 0:30 – 1:00 · The problem, without memory
*Screen:* toggle **Hindsight memory OFF** → **Next invoice** a couple of times → open INV-001 Deccan freight.
"With memory off, every exception lands on a human. Deccan billed ₹2,400 of freight that's not on the PO. The agent
says hold and ask for a PO amendment. Correct in general, wrong for this company. Deccan's contract allows it."

### 1:00 – 2:30 · Live demo, retain → recall
*Screen:* toggle memory **ON** (fresh bank). **Next invoice** on INV-001. In *Why?* type the clause 7.2 / ₹3,000 note →
**Resolve & retain**. Point at the green "Retained to Hindsight" box and the feed on the right.
"Now the AP lead's decision *and her reason* go into Hindsight, tagged with the vendor and the exception type."

*Screen:* **▶ Autopilot** until INV-011 (Deccan ₹2,750), then pause. Open it.
"Five weeks later, Deccan does it again. Look: *Recalled from Hindsight*, the July precedent, 33 days earlier. The agent
checked ₹2,750 against the ₹3,000 cap and auto-resolved, citing it."
Click **Compare without memory** and show both columns side by side. **This is the before/after moment.**

*Screen:* continue to INV-014 Apex.
"Same 6% price increase that was short-paid in July, but the reason said *effective 1 August*. This invoice is dated
10 August, so it approves. Copying the old decision would have been wrong."

*Screen:* continue to INV-020 Deccan ₹6,800. "Over the cap, so it escalates, and suggests paying ₹3,000 freight."
*Screen:* INV-024 Krishna. "Same exception, different vendor. It shows the Deccan pattern as a hint but won't generalise."
*Screen:* finish autopilot. Point at the **Human touches** chart (two lines separating) and the KPIs.
*Screen:* **Ask your AP memory** → "Caps & tolerances" chip (reflect). **Vendor playbook** → Deccan (mental model).

### 2:30 – 3:00 · Takeaway
"What surprised me: my first version remembered the decision, and it copied it straight into a ₹6,800 overpayment.
Remembering the *reason*, with the cap and the date inside it, is what made the agent careful. Code's on GitHub,
built on Hindsight. Link below."

### YouTube titles
1. My AI agent overpaid an invoice, so I changed what it remembers
2. I built an AP agent that learns from every invoice (Hindsight memory)
3. Agent memory done right: retain the reason, not the decision
4. Watch this AI agent stop asking humans the same question twice
5. Stateless LLM vs agent with memory, on real invoice exceptions

### Thumbnail prompt (Prompt 6, paste into Gemini "Create image", attach your photo)
Generate a viral thumbnail for this YouTube video. Make the thumbnail attention grabbing and something that people
scrolling would want to click on if they see it. The aspect ratio needs to be 16:9.
Here is the video script: [paste the script above]
Style hint: the person from the photo on the left looking surprised; on the right a big red stamp "₹6,800 OVERPAID"
crossed out and a green "REMEMBERED WHY ✓"; bold text "MY AGENT REMEMBERED THE WRONG THING".

**Video description:** Precedent, an accounts-payable agent with Hindsight memory. Code: https://github.com/Chetanareddy18/precedent-ap-agent · Hindsight: https://github.com/vectorize-io/hindsight
