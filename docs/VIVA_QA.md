# Viva Questions and Answers

**1. What is Edge AI and how does your project use it?**
Running AI near where data is produced instead of in the cloud. All matching (TF-IDF, cosine similarity, OpenCV) runs on the user's own computer, with no external AI API. We do not claim dedicated edge hardware.

**2. Why is it called agentic?**
Four specialised agents (Intake, Matching, Verification, Notification) each own one task. A coordinator orchestrates them, passes results between them, and branches on outcomes (no match, claim rejected). Each hand-over is logged.

**3. How do the agents communicate?**
Through the coordinator (hub-and-spoke). An agent returns a result; the coordinator passes it to the next agent. Agents never call each other, which keeps them independent and testable.

**4. Explain TF-IDF.**
Term frequency x inverse document frequency. Words frequent in one item but rare overall get high weight; common words get low weight. Each description becomes a vector.

**5. Explain cosine similarity.**
The cosine of the angle between two vectors: 1 means the same direction (very similar text), 0 means nothing in common. It ignores text length.

**6. How is the final score calculated?**
`0.45 x text + 0.25 x metadata + 0.30 x image`; if a photo is missing, `0.60 x text + 0.40 x metadata`. Weights are in `config.py`; threshold 0.40. They are chosen by reasoning and testing on sample data and can be tuned with real data.

**7. How does image matching work?**
Resize to 256x256, blur, build a colour histogram (hue for coloured pixels, brightness for grey ones), compare with Bhattacharyya distance, and match ORB keypoints. Combined 0.6/0.4. It is a suggestion only.

**8. Why not a deep-learning model?**
To stay lightweight, free, offline and explainable on a student PC. A pre-trained CNN (MobileNet through ONNX) is the natural upgrade.

**9. Can image similarity prove ownership?**
No. Many items look alike. That is why a claim, questions, and admin approval are required.

**10. Does AI decide ownership?**
Never. The Verification Agent gives an advisory score; only an administrator approves or rejects.

**11. How are real-time notifications implemented?**
Flask-SocketIO. On connect each logged-in user joins a private room `user_<id>`. The Notification Agent emits `new_notification` to that room; `main.js` updates the bell badge, toast and lists without reloading. Dashboard counters use a `stats_update` event.

**12. Why is Socket.IO in threading mode?**
It works on Windows with the standard development server and no extra packages (eventlet/gevent).

**13. How do you protect passwords and sessions?**
Werkzeug PBKDF2 hashes, server-signed session cookies (HttpOnly, SameSite), session cleared on login to prevent fixation.

**14. How do you secure file uploads?**
Extension allow-list, `secure_filename`, random prefix, 5 MB limit, and OpenCV must decode the file as a real image (a renamed text file is rejected). Uploads are served only to logged-in users.

**15. What is CSRF and how did you stop it?**
A malicious site making your browser submit a form. Every POST requires a per-session random token (form field or header). Our own tests caught and fixed a bug where an empty token matched an empty session.

**16. How is user privacy handled?**
Contacts are hidden until an admin approves a claim; finder's private clue and the AI score are visible only to admins; each user sees only their own matches and claims; real-time events go only to the owner's room.

**17. How does role-based access control work?**
Role is stored in the users table and in the session. `@admin_required` returns 403 for non-admins. Tested in `test_12_unauthorized_access`.

**18. Describe the database design.**
Users, admin, lost_items, found_items, matches (unique lost/found pair), claims, notifications, plus agent_logs. Foreign keys with `PRAGMA foreign_keys=ON`; deleting a report cascades to its matches and claims.

**19. How do you avoid matching an item with itself or the same user's item?**
Candidates come only from the opposite table and exclude the reporter's own user id; the matches table has a UNIQUE(lost_id, found_id) constraint.

**20. What are the limitations?**
TF-IDF is lexical, classical CV is weak for plain objects, dev server only, no rate limiting or password reset. Future work: embeddings, CNN features, email/SMS, HTTPS.

**21. How would it scale?**
Replace SQLite with PostgreSQL, precompute and store feature vectors, use a production server with a message queue for Socket.IO, and pre-filter candidates by category and date before scoring.

**22. How did you test it?**
24 unit and integration tests for the 12 scenarios using synthetic images and Flask's test client, plus a manual two-browser real-time demo.

**23. Where and why did you use YOLO?**
In the Intake Agent: YOLOv8n (pre-trained on COCO, exported to ONNX) detects the main object in each photo. The Matching Agent crops to that object before colour/ORB comparison and adds object-class agreement (both photos show a cell phone) to the image score. It also warns if the chosen category does not fit the photo.

**24. Why ONNX with OpenCV instead of PyTorch?**
It removes the multi-hundred-megabyte PyTorch dependency, installs quickly, and loads in memory-limited servers. We export once, then only OpenCV's DNN module runs inference.

**25. What are YOLO's limits here?**
The standard model has 80 classes: no wallet, keys, documents or jewellery, so those items rely on text and colour matching. It is a suggestion like all image similarity. People are ignored for privacy. If the model file is missing, the system falls back gracefully.

**26. Is a cloud-hosted version still "Edge AI"?**
All inference runs on our own server with no third-party AI API, and the same code runs fully locally on a PC. But once hosted on a cloud server it is no longer running at the user's edge, so describe the hosted version as self-hosted AI and the local version as the Edge AI demonstration.
