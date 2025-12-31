Services
========

תיעוד של שירותי הליבה של המערכת.

Code Service
------------

.. automodule:: services.code_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

GitHub Service
--------------

.. automodule:: services.github_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Backup Service
--------------

.. automodule:: services.backup_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

AI Explain Service
------------------
שירות observability שמפיק הסברים להתראות על בסיס Anthropic Claude עם fallback בין מודלים, סניטציה של לוגים וחיתוך שדות רגישים לפני שליחת ההקשר.

ראו גם :doc:`../api/ai_explain`.

.. automodule:: services.ai_explain_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Community Library Service
-------------------------
ניהול ספריית קוד קהילתית: קליטת מועמדים, אישור/דחייה מול MongoDB, רשימות פומביות עם חיפוש, תגיות וסימון Featured.

.. automodule:: services.community_library_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Image Generator Service
-----------------------
מחולל תמונות קוד מקצועיות עם Pygments, Playwright/WeasyPrint/PIL, מגוון תמות (dark/light/github/monokai וכו') ותמיכה בבחירת פונטים.

.. automodule:: services.image_generator
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Snippet Library Service
-----------------------
מנהל את ספריית הסניפטים המובנית: Built-in snippets, שליחת הצעות, אישור מנהלים, חיפוש לפי שפה/תגיות וסנכרון עם ה-Repo הקיים.

.. automodule:: services.snippet_library_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Observability HTTP Service
--------------------------
עטיפה ליצירת בקשות HTTP מאובטחות אל Grafana/Prometheus תוך מניעת SSRF, אימות DNS Rebinding ושימור Host header עבור SNI.

.. automodule:: services.observability_http
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Google Drive Service
--------------------

.. toctree::
   :maxdepth: 1

   google_drive_service