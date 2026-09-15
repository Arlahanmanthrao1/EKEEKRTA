// Intercepted API fixtures only; never creates real accounts.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const base = process.env.LMS_TEST_URL || 'http://localhost:5173';
    await page.goto(base + '/register');
    await page.getByRole('heading', { name: 'Welcome back' }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/login');
    assert.equal(await page.getByRole('link', { name: 'Create an account' }).count(), 0);
    const admin = { id: 100, name: 'Test Admin', email: 'admin@college.edu', role: 'admin', department: 'CS' };
    let submitted, count = 0, succeed = false;
    await page.route('**/*', async route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization,content-type' };
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      if (pathname === '/auth/me') return route.fulfill({ json: admin, headers });
      if (pathname === '/users/') return route.fulfill({ json: [admin], headers });
      if (pathname === '/courses/') return route.fulfill({ json: [], headers });
      if (pathname === '/institutions/departments') return route.fulfill({ json: [{ id: 1, name: 'Computer Science' }], headers });
      if (pathname === '/erp/configuration') return route.fulfill({ json: { configured: false }, headers });
      if (pathname === '/erp/events') return route.fulfill({ json: [], headers });
      if (!['/auth/register', '/auth/register-faculty'].includes(pathname)) return route.continue();
      const faculty = pathname === '/auth/register-faculty';
      count++;
      assert.equal(request.headers().authorization, 'Bearer isolated-browser-test');
      submitted = request.postDataJSON();
      return route.fulfill({ status: succeed ? 201 : 400, headers,
        json: succeed ? { id: faculty ? 102 : 101, ...submitted, role: faculty ? 'faculty' : 'student' }
          : { detail: 'Email already registered' } });
    });
    await page.evaluate(() => localStorage.setItem('lms_token', 'isolated-browser-test'));
    await page.goto(base + '/');
    const nav = page.getByRole('navigation', { name: 'Dashboard sections' });
    await nav.getByRole('link', { name: 'ERP Integration', exact: true }).click();
    assert.equal(new URL(page.url()).pathname, '/admin/erp');
    await page.getByText('Student master data can be imported from your institution’s ERP').waitFor();
    await nav.getByRole('link', { name: 'Register student', exact: true }).click();
    assert.equal(new URL(page.url()).pathname, '/admin/register-student');
    const studentForm = page.locator('#register-student');
    await studentForm.getByLabel('Full name').fill('Student Test');
    await studentForm.getByLabel('Institution email').fill('student-test@hitam.org');
    await studentForm.getByLabel('Department').selectOption('Computer Science');
    await studentForm.getByLabel('Registration / roll number').fill('STU-TEST-001');
    await studentForm.getByLabel('Program').fill('B.Tech CSE');
    await studentForm.getByLabel('Batch').fill('2026-2030');
    await studentForm.getByLabel('Current semester').selectOption('1');
    await studentForm.getByLabel('Section').fill('A');
    await studentForm.getByLabel('Password', { exact: true }).fill('Test-password-123');
    await studentForm.getByLabel('Confirm password').fill('Test-password-123');
    succeed = true;
    await studentForm.getByRole('button').click();
    await studentForm.getByRole('status').filter({ hasText: 'Student account created' }).waitFor();
    assert.equal(submitted.role, undefined);
    await nav.getByRole('link', { name: 'Create faculty', exact: true }).click();
    assert.equal(new URL(page.url()).pathname, '/admin/register-faculty');
    assert.equal(await page.locator('#register-student').count(), 0);
    const facultyForm = page.locator('#register-faculty');
    await facultyForm.getByLabel('Full name').fill('Faculty Test');
    await facultyForm.getByLabel('Institution email').fill('faculty-test@hitam.org');
    await facultyForm.getByLabel('Department').selectOption('Computer Science');
    await facultyForm.getByLabel('Official employee ID').fill('FAC-TEST-001');
    await facultyForm.getByLabel('Password', { exact: true }).fill('Test-password-123');
    await facultyForm.getByLabel('Confirm password').fill('Different-password-123');
    const before = count;
    await facultyForm.getByRole('button').click();
    await facultyForm.getByRole('alert').filter({ hasText: 'Passwords do not match.' }).waitFor();
    assert.equal(count, before);
    await facultyForm.getByLabel('Confirm password').fill('Test-password-123');
    succeed = false;
    await facultyForm.getByRole('button').click();
    await facultyForm.getByRole('alert').filter({ hasText: 'Email already registered' }).waitFor();
    assert.equal('role' in submitted, false);
    succeed = true;
    await facultyForm.getByRole('button').click();
    await facultyForm.getByRole('status').filter({ hasText: 'Faculty account created' }).waitFor();
    assert.equal(await facultyForm.getByLabel('Password', { exact: true }).inputValue(), '');
    await nav.getByRole('link', { name: 'Users', exact: true }).click();
    const facultyRow = page.locator('#users tr').filter({ hasText: 'faculty-test@hitam.org' });
    await facultyRow.getByText('faculty', { exact: true }).waitFor();
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      for (const label of ['ERP Integration', 'Register student', 'Create faculty']) {
        if (viewport.width < 600) await page.getByRole('button', { name: 'Open left menu' }).click();
        await nav.getByRole('link', { name: label, exact: true }).click();
        const box = await page.locator('main form').boundingBox();
        assert.ok(box.width > 0 && box.x + box.width <= viewport.width + 1);
      }
    }
    console.log('PASS login-only public UI, admin form, authorization, validation, errors, directory update, and responsive sizing');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
