// ESLint for the React frontend (E11, 2026-10-29). `npm run lint`.
// Besides the usual React / hooks checks it enforces the project rule "no
// regex anywhere" (D-046, D-047): no regex literal and no RegExp() — text is
// read with string methods and src/chat/text.js.
import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';

const NO_REGEX = [
  { selector: 'Literal[regex]', message: 'No regex (D-046/D-047): use string methods or src/chat/text.js.' },
  { selector: "NewExpression[callee.name='RegExp']", message: 'No RegExp (D-046/D-047).' },
  { selector: "CallExpression[callee.name='RegExp']", message: 'No RegExp (D-046/D-047).' },
];

export default [
  { ignores: ['node_modules/**', 'undefined/**'] },
  js.configs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    plugins: { react, 'react-hooks': reactHooks },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: '18.3' } },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs['jsx-runtime'].rules,
      ...reactHooks.configs.recommended.rules,
      'react/prop-types': 'off',
      'react/no-unescaped-entities': 'off',
      'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
      'no-restricted-syntax': ['error', ...NO_REGEX],
    },
  },
  {
    files: ['tests/**/*.js', '*.config.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module', globals: globals.node },
    rules: { 'no-restricted-syntax': ['error', ...NO_REGEX] },
  },
];
