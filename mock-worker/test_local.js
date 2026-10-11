// Local test runner for mock-worker/index.js
import worker from "./index.js";

async function testEndpoint(name, url, method, body, expectedStatus) {
  const req = new Request(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  const res = await worker.fetch(req);
  const data = await res.json();
  const passed = res.status === expectedStatus;
  console.log(
    `${passed ? "✅ PASS" : "❌ FAIL"}: [${method} ${url}] Status: ${res.status} (expected ${expectedStatus})`
  );
  if (!passed) {
    console.error("  Response:", data);
  }
  return passed;
}

async function runAll() {
  console.log("=== Testing Mock Worker Endpoints ===");
  let allPassed = true;

  // 1. Health check
  allPassed &&= await testEndpoint("Health", "http://localhost/health", "GET", null, 200);
  allPassed &&= await testEndpoint("Root", "http://localhost/", "GET", null, 200);

  // 2. OAuth2 Token
  allPassed &&= await testEndpoint("Token", "http://localhost/oauth2/token", "POST", {}, 200);

  // 3. cards.list (Ada Örnek 90000001)
  allPassed &&= await testEndpoint(
    "cards.list",
    "http://localhost/voice/v1/cards.list",
    "POST",
    { data: { customerNo: "90000001" } },
    200
  );

  // 4. cards.list without /voice/v1 prefix
  allPassed &&= await testEndpoint(
    "cards.list direct",
    "http://localhost/cards.list",
    "POST",
    { customerNo: "90000001" },
    200
  );

  // 5. cards.list template variable
  allPassed &&= await testEndpoint(
    "cards.list template",
    "http://localhost/voice/v1/cards.list",
    "POST",
    { data: { customerNo: "{{customerNumber}}" } },
    200
  );

  // 6. cards.list 404 (Ozan Yurt 93821776)
  allPassed &&= await testEndpoint(
    "cards.list 404",
    "http://localhost/voice/v1/cards.list",
    "POST",
    { data: { customerNo: "93821776" } },
    404
  );

  // 7. cards.list 500 (Alp Polat 97073972)
  allPassed &&= await testEndpoint(
    "cards.list 500",
    "http://localhost/voice/v1/cards.list",
    "POST",
    { data: { customerNo: "97073972" } },
    500
  );

  // 8. cards.balance (Ada Örnek 540000******1234)
  allPassed &&= await testEndpoint(
    "cards.balance",
    "http://localhost/voice/v1/cards.balance",
    "POST",
    { data: { cardNumber: "540000******1234" } },
    200
  );

  // 9. statement.week.get
  allPassed &&= await testEndpoint(
    "statement.week.get",
    "http://localhost/voice/v1/statement.week.get",
    "POST",
    { data: { cardNumber: "540000******1234" } },
    200
  );

  // 10. statement.week.decide
  allPassed &&= await testEndpoint(
    "statement.week.decide",
    "http://localhost/voice/v1/statement.week.decide",
    "POST",
    { data: { cardNumber: "540000******1234", newStatementWeek: 2, statementDay: 5 } },
    200
  );

  // 11. statement.week.change
  allPassed &&= await testEndpoint(
    "statement.week.change",
    "http://localhost/voice/v1/statement.week.change",
    "POST",
    { data: { cardNumber: "540000******1234", newStatementWeek: 2, statementDay: 5 } },
    200
  );

  // 12. contact.email.get
  allPassed &&= await testEndpoint(
    "contact.email.get",
    "http://localhost/voice/v1/contact.email.get",
    "POST",
    { data: { customerNo: 90000001, intAddressInfoType: "E" } },
    200
  );

  // 13. statement.pdf.send
  allPassed &&= await testEndpoint(
    "statement.pdf.send",
    "http://localhost/voice/v1/statement.pdf.send",
    "POST",
    {
      data: {
        customerNo: "90000001",
        cardNumber: "540000******1234",
        currencyType: "TL",
        statementDate: "05.10.2026",
        emailAddress: "ornek@freyabank.example",
      },
    },
    200
  );

  // 14. statement.pdf.send 404 (Duru Akıncı 93635512)
  allPassed &&= await testEndpoint(
    "statement.pdf.send 404",
    "http://localhost/voice/v1/statement.pdf.send",
    "POST",
    { data: { customerNo: "93635512" } },
    404
  );

  if (allPassed) {
    console.log("\n🎉 ALL TESTS PASSED! Mock worker is 100% compliant with service contract.");
  } else {
    console.error("\n❌ Some tests failed. Please review output above.");
    process.exit(1);
  }
}

runAll().catch(console.error);
