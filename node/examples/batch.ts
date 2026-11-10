import { AlterLab, JobExpiredError } from "alterlab";

async function main() {
  const client = new AlterLab({ apiKey: "sk_test_..." });

  // 1. Submit a batch of URLs
  const batch = await client.batchScrape(
    [
      { url: "https://example.com/page1", mode: "html" },
      { url: "https://example.com/page2", mode: "html" },
      { url: "https://example.com/page3", render_js: "auto" },
    ],
    "https://myapp.com/webhook", // optional webhook
  );
  console.log(`Batch ID: ${batch.batch_id}`);
  console.log(`Jobs: ${batch.job_ids.length}`);

  // 2. Wait for all jobs to complete
  // Job results are available for 1 hour. If a job has expired, waitForJob
  // throws JobExpiredError — catch it to avoid retrying with a stale job ID.
  for (const jobId of batch.job_ids) {
    try {
      const result = await client.waitForJob(jobId, { pollTimeout: 60000 });
      console.log(`  Job ${jobId}: ${result.result?.content.length} chars`);
    } catch (e) {
      if (e instanceof JobExpiredError) {
        console.error(
          `  Job ${e.jobId} expired before polling started. Submit a new request.`,
        );
      } else {
        throw e;
      }
    }
  }

  // 3. Or check status without waiting
  // getJobStatus also throws JobExpiredError on 404.
  for (const jobId of batch.job_ids) {
    try {
      const status = await client.getJobStatus(jobId);
      console.log(`  Job ${jobId}: ${status.status}`);
    } catch (e) {
      if (e instanceof JobExpiredError) {
        console.error(`  Job ${e.jobId} has expired.`);
      } else {
        throw e;
      }
    }
  }
}

main().catch(console.error);
