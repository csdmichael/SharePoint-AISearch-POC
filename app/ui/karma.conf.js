// Karma configuration for the Angular unit tests (Jasmine on ChromeHeadless).
// Chrome is located by karma-chrome-launcher (CHROME_BIN or the standard install paths).
module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
    ],
    client: {
      jasmine: {
        random: true,
      },
      clearContext: false,
    },
    reporters: ['progress'],
    browsers: ['ChromeHeadless'],
    customLaunchers: {
      ChromeHeadless: {
        base: 'Chrome',
        flags: ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      },
      ChromeHeadlessCI: {
        base: 'Chrome',
        flags: ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      },
    },
    browserNoActivityTimeout: 120000,
    captureTimeout: 120000,
    singleRun: true,
    restartOnFileChange: false,
  });
};
