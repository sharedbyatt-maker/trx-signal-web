/* Bound the complete request, including body parsing, so polling always recovers. */
window.TRXNet = (() => {
  async function run(operation, timeoutMs = 8000) {
    const controller = new AbortController();
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error('Request timed out'));
      }, timeoutMs);
    });
    try { return await Promise.race([operation(controller.signal), deadline]); }
    finally { clearTimeout(timer); }
  }
  return {run};
})();
