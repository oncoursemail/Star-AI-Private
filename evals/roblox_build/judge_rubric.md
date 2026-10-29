# Blind judge rubric: Roblox environment builds

You see packets P01..P12. Each packet image shows two builds of the same brief: BUILD A (top row) and BUILD B
(bottom row), each as 4 camera shots (eye-level hero view from the spawn, wide view, detail view, overview).
`packets.txt` gives the brief and the target art style (stud = classic studded blocks; lowpoly = faceted flat
colour; midpoly = believable materials and moderate detail; highpoly = dense detail, layered lighting).

Score each build 1-10 against a professional Roblox environment portfolio (10 = portfolio-ready, 5 = competent
hobby build, 1 = broken/empty). Judge only what you see:
- brief fit (the requested places and objects are there and read clearly)
- composition (focal point, leading lines, framing, depth)
- scale vs a 5-stud character
- lighting and mood
- detail density and storytelling with intent (not empty, not random noise)
- style consistency for the target style, colour/material discipline
- cleanliness (no floating/clipping parts, no obvious errors, no black or broken shots)

Be strict and use the whole range. Ties are allowed. Answer per packet:
`{"packet": "P01", "A": n, "B": n, "better": "A|B|tie", "why": "one short sentence"}`
and at the end one JSON list of all 12 objects.
