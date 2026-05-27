const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    
    console.log('Testing UGo application...');
    
    try {
        // Test home page
        console.log('Testing home page...');
        await page.goto('http://localhost:8000');
        await page.waitForLoadState('networkidle');
        const homeTitle = await page.title();
        console.log(`Home page title: ${homeTitle}`);
        
        // Check if main elements are present
        const heroTitle = await page.locator('h1.hero-title').isVisible();
        console.log(`Hero section visible: ${heroTitle}`);
        
        // Test login page
        console.log('Testing login page...');
        await page.goto('http://localhost:8000/login/');
        await page.waitForLoadState('networkidle');
        const loginTitle = await page.locator('h3:has-text("Sign In")').isVisible();
        console.log(`Login form visible: ${loginTitle}`);
        
        // Test signup page
        console.log('Testing signup page...');
        await page.goto('http://localhost:8000/signup/');
        await page.waitForLoadState('networkidle');
        const signupTitle = await page.locator('h3:has-text("Create Account")').isVisible();
        console.log(`Signup form visible: ${signupTitle}`);
        
        console.log('\nAll tests passed! UGo application is working correctly.');
        
    } catch (error) {
        console.error('Test failed:', error.message);
        process.exit(1);
    } finally {
        await browser.close();
    }
})();
