import '@testing-library/jest-dom/vitest';
import { webcrypto } from 'node:crypto';
if (!globalThis.crypto?.subtle) Object.defineProperty(globalThis, 'crypto', { value: webcrypto });
// jsdom has no WebGL: the orb draws nothing in tests
HTMLCanvasElement.prototype.getContext = (() => null) as never;
