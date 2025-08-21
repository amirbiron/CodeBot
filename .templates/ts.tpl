/**
 * File: {{FILENAME}}
 * Created: {{DATETIME}}
 * Author: {{AUTHOR}}
 * Description: {{DESCRIPTION}}
 */

function main(): void {
}

// If running under Node
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const g: any = globalThis as any;
if (g?.process?.argv && g?.require?.main === module) {
  main();
}

export {};
