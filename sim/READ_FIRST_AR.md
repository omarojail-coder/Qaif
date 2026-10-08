# إعادة تشغيل الإصدار 0.4.0

حزمة `simulator_0_4_0_reproducible.zip` لقطة كاملة من حزمة المحاكي والأمثلة والسجلات والمدخلات المؤرشفة المستخدمة، مع قناة ضغط Cheyenne اللازمة لأداة التوليد. لا تضم بيئة Python أو نموذج إنذار أو مكتبات خارجية. فك الضغط إلى مجلد جديد ثم افتح PowerShell في جذر المجلد.

تشغيل المحاكي والدراسة والاختبارات يتطلب Python 3.10 أو أحدث ويستخدم المكتبة القياسية فقط. إعادة استخراج PDF الأصلي عبر `additional_sources` تحتاج pypdf، لكن CSV المستخرج والملفات الأصلية موجودة؛ لا تحتاج pypdf أو الإنترنت لإعادة توليد الدراسة من الأرشيف.

```powershell
python -X utf8 -m unittest discover -s qaif_saddle_sim/tests -v
python -X utf8 -m qaif_saddle_sim.build_validation_study --out outputs/rebuilt_validation_study
python -X utf8 -m qaif_saddle_sim.coherence_audit --study outputs/rebuilt_validation_study --out outputs/rebuilt_coherence.json
python -X utf8 -m qaif_saddle_sim.physics_validation --config outputs/rebuilt_validation_study/bases/coast_rain/config.json --forcing outputs/rebuilt_validation_study/bases/coast_rain/forcing.csv --out outputs/rebuilt_physics.json
```

المولد يرفض مجلدًا غير فارغ. محفوظاته الأساسية تشمل summary/coherence/source_groups والتحقق الحراري لكل أساس وتدقيق كل زوج. التقرير العربي وعقد القياسات والاتحاد النهائي في حزمة التسليم الحالية أُضيفت بعد التوليد وتضم نتائج إعادة التدقيق؛ لا تنتج تلقائيًا من أمر التوليد وحده.

إذا جُمعت النتائج الجديدة مع نتائج أخرى، أعد حساب الاتحاد من أصول المصادر:

```powershell
python -X utf8 -m qaif_saddle_sim.global_source_audit --study PATH_TO_FIRST_STUDY --study PATH_TO_SECOND_STUDY --study PATH_TO_THIRD_STUDY --out outputs/combined_sources.json
```

الأرشيف الحالي يجمع الدراسة الجديدة وevidence_study_v3 وpressure_resume_v1 في مكوّن واحد؛ لا تعتمد على رقم المجموعة المحلي أو seed لتحديد الاستقلال. ملف `source_code_sha256.json` يوثق الشيفرة الحالية، و`reproducible_bundle_manifest.json` يوثق جميع أعضاء ZIP وبصماتهم؛ تحقق CRC والبصمات لكل الأعضاء بعد إنشاء الحزمة. `files_sha256.json` يغطي ملفات التسليم النهائية ولا يضم نفسه.

هذه الحزمة تُعيد المنهج والبيانات المؤرشفة، ولا تمنح صلاحية نقل النتيجة إلى سرج فعلي. قياسات المصدر التاريخي وما قبل الحادث لا تمثل إثبات سلامة تشغيل أو قياس سرج سعوديًا.
