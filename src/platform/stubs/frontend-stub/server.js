// Minimal stub frontend that responds to health checks.
// Replaced by real Next.js frontend from Frontend workstream when available.

const http = require("http");
const port = parseInt(process.env.PORT || "3000", 10);

const server = http.createServer((req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end('{"status":"ok","stub":true}');
  } else if (req.url === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end("<html><body><h1>AI-First LMS — Stub Frontend</h1><p>Waiting for Frontend workstream.</p></body></html>");
  } else {
    res.writeHead(404);
    res.end();
  }
});

server.listen(port, "0.0.0.0", () => {
  console.log(`Frontend stub listening on :${port}`);
});
