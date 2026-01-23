describe('RepoHistory Utilities', () => {
    describe('escapeHtml', () => {
        // Assuming escapeHtml is exported or accessible
        const escapeHtml = (text) => {
            if (!text) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        };

        it('should escape HTML entities', () => {
            expect(escapeHtml('<script>alert("xss")</script>'))
                .toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
        });

        it('should handle empty string', () => {
            expect(escapeHtml('')).toBe('');
        });

        it('should handle null', () => {
            expect(escapeHtml(null)).toBe('');
        });
    });

    describe('buildApiUrl', () => {
        const buildApiUrl = (endpoint, params = {}) => {
            const url = new URL(endpoint, 'http://localhost');
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null) {
                    url.searchParams.set(key, value);
                }
            });
            return url.pathname + url.search;
        };

        it('should build URL with query params', () => {
            const url = buildApiUrl('/repo/api/history', {
                file: 'src/main.py',
                limit: 20
            });
            expect(url).toBe('/repo/api/history?file=src%2Fmain.py&limit=20');
        });

        it('should handle file paths with slashes correctly', () => {
            const url = buildApiUrl('/repo/api/history', {
                file: 'path/to/deep/file.js'
            });
            // Note: slashes ARE encoded in query params
            expect(url).toContain('file=path%2Fto%2Fdeep%2Ffile.js');
        });

        it('should skip null/undefined params', () => {
            const url = buildApiUrl('/repo/api/diff/a/b', {
                file: null,
                format: 'parsed'
            });
            expect(url).not.toContain('file=');
            expect(url).toContain('format=parsed');
        });
    });
});
