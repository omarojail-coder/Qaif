# محاكي سرج «قائف» — نواة قابلة للتشغيل

**آخر مرحلة مكتملة — 0.4.0، 2 أكتوبر 2026:** أُضيف أصل GasLibE-39 ومصدر ضغط NTSB San Bruno، وتحقق مستقل لمعادلات الانفعال والحرارة، وفحوص اختصارات بترك مجموعة المصدر خارج التدريب التشخيصي، وأداة مقارنة بقياسات مستقلة. المصفوفة الجديدة 69 زوجًا = 138 تشغيلًا على أربعة أسس وملفَّي حساس. جميع النتائج `training_ready=false`. المجموعة الجديدة وحدها لها مكوّنان؛ دمجها مع التجارب السابقة يربطهما في مكوّن واحد، ولذلك لا يوجد تقسيم train/validation/test صالح. تفاصيل التنفيذ في [حالة الاستئناف](PROGRESS_2026-10-02.md).

### أوامر المرحلة 0.4.0

الأرشيف الإضافي موجود في `reference_data/additional_v1`؛ لا تتطلب إعادة التوليد اتصالًا بالشبكة. تُشغل الأوامر من مجلد المشروع الأصلي، ويجب أن يكون مجلد التوليد جديدًا أو فارغًا:

```powershell
python -X utf8 -m qaif_saddle_sim.build_validation_study --out outputs/new_validation_study
python -X utf8 -m qaif_saddle_sim.coherence_audit --study outputs/new_validation_study --out outputs/new_validation_study/coherence_reaudit.json
python -X utf8 -m qaif_saddle_sim.physics_validation --config outputs/new_validation_study/bases/coast_rain/config.json --forcing outputs/new_validation_study/bases/coast_rain/forcing.csv --out outputs/new_validation_study/physics_reaudit.json
python -X utf8 -m qaif_saddle_sim.global_source_audit --study outputs/new_validation_study --study PATH_TO_PREVIOUS_EVIDENCE_STUDY --study PATH_TO_PREVIOUS_PRESSURE_STUDY --out outputs/new_validation_study/global_source_audit.json
python -X utf8 -m qaif_saddle_sim.measurement_validation --simulated PATH_TO_SIMULATION_BRANCH --measurements PATH_TO_MEASURED_CSV --metadata PATH_TO_MEASUREMENT_METADATA --out outputs/measurement_comparison.json
```

آخر أمر يتطلب قياسات فعلية ووثيقة مصدر وبروتوكول ووحدات وحدود مقارنة محددة مسبقًا. يقارن RMSE والانحياز بعد التحقق من البصمات والمحاذاة الزمنية؛ لا يقدّر معاملات `gain/lag` تلقائيًا ولا يحوّل نجاح المقارنة إلى اعتماد ميداني. قالب العقد وتقرير المرحلة في مجلد المحادثة الحالية `outputs/validation_study_v1`.

صُحح في 0.4.0 أثر الانحناء المحوري على الانفعال المحيطي بإضافة اقتران بواسون `Δεh = -ν Δεa`. تحققنا من بقاء ملفات تشغيل ضابط كامل بلا انحناء متطابقة بالبايت مع 0.3.0. التسريع يستخدم ذاكرة محدودة لحالات الفيزياء المتطابقة تمامًا؛ حالة الحساس والضجيج لا تُشارك بين التشغيلات، وقورنت نتيجة 72 ساعة بالحساب دون ذاكرة ووجدت متطابقة. أحداث المسار تُقيَّم عند طوابع العينات وتُثبّت خلال الفترات؛ ليست أحداثًا محلولة في الزمن المستمر.

هذا البرنامج يولّد **سلاسل زمنية اصطناعية** لقناتي إجهاد اتجاهيتين، وحرارة خارجية، ومؤشر بلل محلي. الإصدار الحالي أداة لتجريب اتساق الإشارات وبناء مسار البيانات، وليس بيانات تدريب معتمدة أو إثباتًا لمدى الكشف. أرقام المثال `examples/fixture_*` قيم فحص برمجي، وليست معايرة للسرج أو تصميمًا نهائيًا له.

## التشغيل

من مجلد المشروع الرئيسي وبـ Python 3.10 أو أحدث، دون حزم إضافية:

```powershell
python -m unittest discover -s qaif_saddle_sim/tests -v
python -m qaif_saddle_sim.cli simulate --config qaif_saddle_sim/examples/fixture_config.json --forcing qaif_saddle_sim/examples/fixture_forcing.csv --out outputs/my_saddle_run --seed 42
```

لإنشاء **نسخة ضابطة ونسخة حدث** من الضغط والطقس نفسيهما:

```powershell
python -m qaif_saddle_sim.cli pair --config qaif_saddle_sim/examples/fixture_config.json --forcing qaif_saddle_sim/examples/baseline_forcing.csv --intervention qaif_saddle_sim/examples/wetting_intervention.json --out outputs/my_saddle_pair --seed 42
```

لمسار زمني **متعدد المراحل** فوق حلقة الأساس نفسها:

```powershell
python -m qaif_saddle_sim.cli timeline --config qaif_saddle_sim/examples/fixture_config.json --forcing qaif_saddle_sim/examples/baseline_forcing.csv --timeline qaif_saddle_sim/examples/wetting_timeline.json --out outputs/my_saddle_timeline --seed 42
```

مثال `wetting_timeline.json` للفحص البرمجي فقط: بداية فتح مسار الماء مع تغير تدريجي في دافع البلل، ثم استمرار المسار مفتوحًا، ثم مرحلة مراقبة تعافٍ بلا تدخل جديد؛ يغلق المسار عند انتهاء مرحلة الفتح وتبقى حالة البلل إلى أن تجف. قيم الأوقات والشدة **ليست مستخرجة من QC-02**. تستخدم الفروع الضابطة والتدخل المعادلات والبذرة والإعدادات نفسها.

`--out` يجب أن يكون مجلدًا جديدًا أو فارغًا؛ لا يكتب البرنامج فوق نتائج قديمة. يحتفظ كل تشغيل بنسخة ملف الضبط والمدخلات وبصمات SHA-256 في `manifest.json`.

### مدخلات طقس وتشغيل معيارية مؤرشفة

انظر [توثيق ربط المصادر](REFERENCE_INTEGRATION.md). الملفات الأصلية الإحدى عشرة وبصماتها موجودة في [reference_data/source_manifest.json](reference_data/source_manifest.json)، لذا لا يلزم الاتصال بالإنترنت للتشغيل. تتضمن سنتَي موقع كاملتين من 2024 وست حلقات أسبوعية مختارة، وشبكة GasLib-134 وحالة/حدود تشغيل TRR154. لإعداد حلقة جديدة في مجلد فارغ ثم تمريرها إلى المحاكي:

```powershell
python -m qaif_saddle_sim.cli prepare-reference --sources qaif_saddle_sim/reference_data --episode red_sea_coast_rain_2024 --template qaif_saddle_sim/examples/reference_template_config.json --gas-assumptions qaif_saddle_sim/examples/reference_gas_assumptions.json --out outputs/my_reference_inputs
python -m qaif_saddle_sim.cli simulate --config outputs/my_reference_inputs/config.json --forcing outputs/my_reference_inputs/forcing.csv --out outputs/my_reference_sim --seed 42
```

يمكن استخدام الحلقة نفسها مع `pair` أو `timeline`. يتحقق البرنامج من بصمات المصدر وملفي الضبط والمدخلات، ثم ينسخ `reference_manifest.json` إلى النتيجة. `source_diagnostics.csv` معلومات تدقيق فقط. يحوي ملف المدخلات 169 صفًا لأسبوع ذي 168 ساعة: صف تهيئة ثم صف نهاية كل ساعة. `training_ready=false` لأن طقس POWER والشبكة المعيارية لا يعايران استجابة سرج لم يُصنع.

### تدقيق ضغط تشغيلي أمريكي مستقل

استُخرجت قناتا ضغط من [ملف NTSB لحادث Cheyenne](https://data.ntsb.gov/Docket?ProjectID=201060): قناة `57035` بوحدة `PSIG` المصرّح بها، وقناة `1067220` التي لا يذكر جدولها الوحدة. يوثق [تقرير التدقيق التاريخي](../outputs/ntsb_pressure_audit_v1/AUDIT.md) المقارنة النسبية مع المسار الدوري القديم، ويضم [اختبار استجابة مستقل](../outputs/ntsb_pressure_audit_v1/holdout_stress/stress_report.json) لنافذة الهبوط مقابل ضغط ثابت. **نافذة الحادث وما بعدها تبقى محجوبة** ولا تدخل التدريب أو ضبط المعلمات. المسار الجديد أدناه يستخدم نافذة سابقة للحادث لتجربة تغير الضغط فقط، وهي ليست تشغيلًا سليمًا موثقًا أو قياس سرج.

### مسار ضغط غير دوري — استئناف 2 أكتوبر 2026

الافتراضي `--pressure-mode periodic_benchmark_surrogate` يبقي قيم المسار القديم كما هي ويسجل دوريّته. المسار الاختياري `ntsb_relative_upstream` ينقل **نسب وسيط الضغط الساعي في وحدته الأصلية** إلى ضغط منبع الأنبوب المرجعي، ثم يطبق معادلة الضغط المحلية نفسها. لا ينقل تدفقًا من NTSB؛ التدفق يبقى `periodic_trr154_demand_surrogate`.

```powershell
python -m qaif_saddle_sim.cli prepare-reference --sources qaif_saddle_sim/reference_data --episode red_sea_coast_rain_2024 --template qaif_saddle_sim/examples/reference_template_config.json --gas-assumptions qaif_saddle_sim/examples/reference_gas_assumptions.json --pressure-mode ntsb_relative_upstream --ntsb-pressure-dir outputs/ntsb_pressure_audit_v1/west_spill_1067220 --ntsb-start-local "2025-09-13 15:00" --out outputs/new_nonperiodic_inputs
python -m qaif_saddle_sim.cli simulate --config outputs/new_nonperiodic_inputs/config.json --forcing outputs/new_nonperiodic_inputs/forcing.csv --out outputs/new_nonperiodic_sim --seed 42
python -m qaif_saddle_sim.cli audit-reference --prepared outputs/new_nonperiodic_inputs --simulated outputs/new_nonperiodic_sim
python -m qaif_saddle_sim.build_pressure_comparison --out outputs/new_pressure_comparison
```

يتحقق الموصل من بصمة PDF الأصلي وCSV القناة، ويرفض ساعة فارغة، أو نافذة تمتد إلى ما بعد بداية الساعة المحجوبة `2025-09-20 23:00`، أو قيمة منبع خارج حدود المصدر المعياري؛ لا يكرر النافذة ولا يستوفي الفجوات ولا يقص الضغط. `--ntsb-start-local` ساعة المصدر **المحلية** لا UTC؛ النافذة تقترن بطقس POWER المختلف حسب الساعات المنقضية فقط، ولا تمثل قياسات متزامنة. يحتاج المصدر عدد ساعات يساوي حلقة الطقس؛ للأرشيف السنوي استخدم `--window-start-utc` و`--window-hours` لاختيار نافذة مناسبة.

النافذة الافتراضية في أداة المقارنة: `[2025-09-13 15:00, 2025-09-20 15:00)`، 168 ساعة مكتملة في West Spill؛ قناة PSIG لا تصلح لهذه النافذة بسبب ساعات فارغة. `pressure_hourly_snapshot.csv` و`source_diagnostics.csv` تدقيق فقط، ولا يدخل وقت المصدر أو القناة أو صفحاتها إلى `observed/context`. تُسجل البصمات والتجميع والفجوات والتحويل وحدوده في `reference_manifest.json` إصدار 2.

تولد أداة المقارنة 12 تشغيلًا لست حلقات طقس، لكنها تعيد استخدام **نافذة ضغط مستقلة واحدة**. جميع قنوات/نوافذ Cheyenne ومشتقاتها، مع فروعها وسياقات الطقس، تبقى في المجموعة نفسها عند أي تقسيم لاحق. لم تُنشأ مجموعة تدريب ولم تتغير `training_ready=false`. انظر التفاصيل في [REFERENCE_INTEGRATION.md](REFERENCE_INTEGRATION.md).

يحدد `effective_axial_exposure_length_m` في ملف افتراضات الغاز حساب حرارة الغاز المحلية: `0` يثبت حرارة المرجع، و`100` أو `1000` م يفعّلان مسح تبادل الحرارة المحوري. هذه **أطوال افتراضية وليست طول كشف السرج**. أداة `python -m qaif_saddle_sim.build_axial_sensitivity` تعيد مقارنة أسبوعين صيفيين بثلاثة أطوال في مجلد جديد. [نتائج المقارنة](../outputs/axial_sensitivity_v2/summary.json) موثقة ولا تُعد بيانات تدريب لأعطال حقيقية.

### ربط تجربة ببطاقة حالة حقيقية

تضم [بطاقات الحالات](CASE_CARDS_V1.md) ست حالات مفروزة، ويحتوي `case_registry.json` قرار قابلية ربط كل منها بحدث حالي. يمكن إضافة `"inspired_by_case_id": "QC-02"` إلى ملف التدخل في أمر `pair` الخاص ببلل الواجهة. يُنسخ سجل البطاقة وبصمته إلى `inputs/case_card_snapshot.json` و`paired_manifest.json`. الربط يوثّق **مصدر فكرة الآلية فقط**؛ قيم `set` وتوقيتاتها يجب تبريرها بشكل مستقل ولا تُنسب إلى الحادثة. يرفض البرنامج ربط حالات الاستبعاد أو الحالات التي تحتاج نموذجًا مكانيًا بنوع حدث غير مدعوم. معرف الحالة لا يدخل `observed.csv` أو `context.csv`.

## ما يحسبه

### سجل الأدلة ومصفوفة البحث — الإصدار 0.3.0

السجل الفعلي في [evidence/parameter_registry.json](evidence/parameter_registry.json)، ويغطي 68 حقلًا عدديًا فعليًا في config/افتراضات الغاز، بما فيها القيم الافتراضية المضمرة، إضافة إلى أربع معلمات سيناريو. يثبت كل سجل الوحدة والاسمي ونقاط المسح وحالة الدليل وحدود النقل. **نقاط المسح اختيارات بحثية معلنة وليست نطاقات قياس أو فواصل ثقة**. تُراجع المراجع العامة للفولاذ كمرتكز مقارنة؛ الطلاء واللاصق والكسب والبلل والضجيج ما زالت غير معايرة.

[evidence/profiles.json](evidence/profiles.json) يربط أصل GasLib المعياري فوق الأرض بملفَي طقس شبكيين، دون اختلاق درجة فولاذ أو ترتيب دعامات أو معدل أعطال لكل موقع. يتحقق البرنامج من البصمات والقطر والإحداثيات وUTC، ويرفض أصلًا مدفونًا أو احتمال أعطال مفترضًا في ملف الموقع.

```powershell
python -m qaif_saddle_sim.build_evidence_study --out outputs/new_evidence_study
```

يبني الأمر أربع نوافذ من 72 ساعة (مطر/صيف الموقعين) ويعيد بناء المدخل الساعي بثباته خلال الساعة على شبكة داخلية 600 ثانية؛ **لا تُنشأ دقة قياس مصدر جديدة**. معاملات الضجيج AR(1) واحتمال فقد الحزمة معرفان لكل عينة محاكاة، لذلك تغيير فترة العينة يغير تفسيرهما الزمني؛ ليس هناك معايرة لطيف الضجيج أو معدل اتصال مستمر. يمكن اختيار `--period-s 300` أو `1800` لمسح الدقة المعلنة.

تُولد أزواج لعزم محلي، انخفاض اقتران القراءة، انقطاع حزم، تسطح حساس بلل، وفتح مسار ماء خلال هطول موجود أصلًا. تشترك عائلات الآليات في أوقات البدء والمدد داخل كل نافذة، وتثبت الضوابط الضغط والطقس والبذرة والهندسة. تتحول حدود مراحل timeline إلى صف نهاية الفترة التالي حتى تتفق بداية المؤثر مع الفترة الفيزيائية المقصودة. يشمل `study_audit` تطابق ما قبل التدخل والسياق، فحص الإجهاد على محيط الأنبوب تحت ميزانية بحثية مفترضة، وثبات فيزياء الأصل في أعطال الحساس.

المسوح أحادية العامل على 14 محورًا تعطي 29 تشغيلًا تشمل الاسمي. تُسجل المقارنات لكل قناة بوحدتها، ولا يُفسر حجم القطاع الحراري على أنه مدى كشف. محفوظة في `sensitivity/` مع مصدر الحلقة وملفات الضبط والمدخلات والبصمات.

`source_groups.json` يبني المجموعات العابرة للعلاقات: أصل مشترك أو مصدر ضغط/طقس مشترك يربط الفروع والمسوحات قبل التقسيم. توجد حاليًا مجموعة مترابطة واحدة فقط، لذا لا ينشئ الأمر train/validation/test ولا يدرب نموذجًا. تُحصر النسخ المتطابقة عمدًا (الضوابط ونسخة QC-02) ولا تُحسب كعينات مستقلة. المخرجات مجموعة تجارب بنية/حساسية، وكلها `training_ready=false`.

أُصلح في 0.3.0 خلل جعل `force_missing` يتخطى سحبًا عشوائيًا، فيغير ضوضاء القراءة بعد انتهاء الانقطاع. الآن يثبت مسار السحب في الفرعين؛ القراءات بعد استعادة الاتصال تتطابق عند ثبات الفيزياء والمدخلات. التشغيلات القديمة تبقى محفوظة بإصدارها؛ لا تغير هذه المراجعة قيم التشغيل العادي الذي لا يحوي فقدًا مفروضًا.

- **الأنبوب:** أنبوب فولاذي مطلي فوق الأرض، في المجال المرن، بجدار رقيق `D_i/t > 20`. للإغلاق الطرفي: `σ_hoop=P D_i/(2t)` و`σ_axial=P D_i/(4t)`. تُضاف حرية التمدد الحراري/قيد محوري مثالي وعزم انحناء يُقدَّم **عند موضع السرج**. لا يحسب البرنامج انتقال العطل على طول الأنبوب. معادلات الضغط تتسق مع [هذا المثال المنشور لأنبوب رقيق](https://pmc.ncbi.nlm.nih.gov/articles/PMC9413821/)؛ لا تُنقل حساسية الحساس في الورقة إلى سرج قائف.
- **الحرارة:** عقدتان حجميتان للفولاذ والطلاء في **قطاع زاوي يحدده الإدخال** `thermal_sector_angle_rad`، ومقاومات أسطوانية بين المائع والجدار والسطح، ثم توازن السطح بالحمل إلى الهواء والإشعاع إلى السماء وكسب الشمس. `solar_incidence` متوسط عامل التعرض داخل ذلك القطاع. التكامل صريح بخطوات زمنية داخلية مقيدة بحجم ثابت الزمن. يتجاهل هذا النموذج انتقال الحرارة جانبيًا عبر حدود القطاع؛ ليست هذه خريطة حرارية ثلاثية الأبعاد لشكل السرج.
- **البلل:** متغير كامن بين 0 و1 يرتفع فقط عند وجود `wet_path_open=1` ودافع بلل `wet_drive>0`، ويجف بمعدل محدد. معناه بلل **واجهة قياس مصممة**؛ ليس عمق تآكل أو كشف ماء تحت كل طلاء سليم.
- **قراءة السرج:** اتجاه حساس الإجهاد، الكسب/الاقتران، زمن الاستجابة، تأثير الحرارة المتقاطع، الانحياز، الانجراف، ضجيج مترابط، تسطح القراءة وفقد الحزمة. كسب الحرارة يضرب **الانحراف عن الحرارة المرجعية**، لا قيمة Kelvin المطلقة. وحدتا الإجهاد `microstrain` والحرارة `K`؛ يمكن تحويل الأخيرة إلى °C بطرح `273.15`. قيمة البلل مؤشر مجرد `[0,1]`، وليست pF أو MHz.

المعلمات الهندسية والحسية كلها مدخلات في JSON، وليس في الشيفرة ثوابت معايرة لسرج لم يُصنع. `active_length_m` و`thermal_sector_angle_rad` يحددان حجم المنطقة الحرارية المحسوبة؛ **لا يعنيان مدى تغطية أو مسافة كشف**.

## المدخلات والملفات

`config.json` يثبت هندسة الأصل، المواد، موضع الحساس الزاوي، معاملات انتقال القراءة، والقنوات التشغيلية المتاحة فعلًا للنظام في `observable_context`. يمكن للقائمة الأخيرة احتواء `pressure_pa`, `fluid_temperature_k`, `ambient_temperature_k`, `solar_w_m2`, `solar_incidence` فقط؛ أزل أي قناة لن تتوفر وقت التشغيل.

`forcing.csv` يتبع أعمدة [المثال](examples/baseline_forcing.csv). الوقت بالثواني ومتزايد قطعًا؛ الضغط Pa؛ الحرارة K؛ الشمس W/m²؛ معاملا الحمل W/(m²·K)؛ عزم الانحناء N·m؛ والزوايا rad. الحقول المنطقية تكتب `0` أو `1`. `event_type` وحقول التحكم بعطل الحساس وسلوك البلل معروفة للمولد فقط، وليست مدخلات تدريب.

| ملف الخرج | الاستخدام |
|---|---|
| `observed.csv` | أربع قنوات يراها النظام + `packet_valid`؛ بلا معرف أصل أو تشغيل |
| `context.csv` | مدخلات تشغيل/بيئة مصرّح بأنها قابلة للتوفر عند التشغيل؛ بلا معرف أصل أو تشغيل |
| `latent.csv` | الحالة الفيزيائية والأوسمة الحقيقية لمراجعة المحاكي والتقييم فقط |
| `config_snapshot.json`, `forcing_snapshot.csv` | إعادة إنتاج التجربة؛ لا تضمهما إلى ميزات النموذج |
| `manifest.json` | الإصدار والبذرة والبصمات وحدود الاستخدام |

عند فقد حزمة تكون القيم المقروءة فارغة ويظل صف الحالة الكامنة موجودًا. لا تُوصل `latent.csv` أو `event_type` إلى مدخلات النموذج. في التشغيل المزدوج، `paired_manifest.json` يحمل `split_group` مشتركًا؛ يجب إبقاء نسختَي الحلقة في **القسم نفسه** عند تقسيم البيانات.

في أمر `timeline` تُحفظ `inputs/timeline_spec.json` و`inputs/timeline_samples.csv` للمراجعة فقط. يحمل الأخير اسم المرحلة والحقول التي تغيرت عند كل عينة؛ **ليس ملف ميزات أو وسم عطل جاهزًا للتدريب**. توقف التدخل لا يعني اختفاء أثره: قد تبقى قراءة البلل مرتفعة أثناء التعافي بفعل حالة الواجهة وزمن استجابة الحساس. تُعرّف وسوم المهمة لاحقًا من الآلية والحالة الفيزيائية والمعنى التشغيلي المطلوب، لا من `intervention_applied` وحده. تظل المعرّفات وبطاقة الحالة في `paired_manifest.json` وملفات الإدخال. الوقت في `observed.csv` و`context.csv` لمحاذاة العينات؛ لا يُغذى رقم العينة أو وقت بدء تدخل ثابت إلى النموذج دون اختبار خطر اختصار التوقيت.

## صنع حلقات مزدوجة

ينبغي أن يحتوي ملف الأساس على `normal_operation` و`normal_environment` فقط. ملف التدخل JSON يحدد `event_type`, `start_s`, `end_s` وقيم `set` التي تحل محل الحقول خلال الفترة `[start_s,end_s)`. مثلًا يفتح مثال البلل مسار ماء عندما يكون دافع البلل موجودًا أصلًا في ملف الطقس. ولحدث ميكانيكي، يمكن وضع `"bending_moment_nm": 20` مع وسم `mechanical_change`، مع توثيق مصدر القيمة لاحقًا. تسمية الحدث تحدد آلية الاختبار فقط؛ **لا تثبت** أنه شق أو فقد جدار.

### وصف المسار الزمني

يحتوي JSON على `schema_version: "1"` و`asset_id` المطابق لملف الضبط، و`base_episode_id` المطابق لـ`source_episode_id`، و`site_id`، و`scenario_family_id`، و`mechanism_id`، وقائمة `phases`. `site_id` معرف توثيقي؛ دراسات البحث تربطه بحلقات طقس شبكية مؤرشفة، لا بموقع أنبوب فعلي مقاس. يمكن وضع `inspired_by_case_id` الاختياري، مع فحص سماح سجل الحالات بالآلية المختارة. ويمكن تسجيل `evidence_level` و`unknown_assumptions` لمصدر القيم وحدودها. يجب أن تحتوي القائمة مرحلة واحدة على الأقل من نوع `mechanism_id`.

لكل مرحلة `phase_id` فريد، و`event_type`، و`start_s`، و`end_s`، و`changes`. الفترات `[start_s,end_s)` مرتبة ولا تتداخل؛ أي فراغ يعيد مدخلات الأساس، بينما تحتفظ حالة المحاكي الفيزيائية بتاريخها. تُحدَّد كل قيمة في `changes` بواحد من:

- `{"mode":"hold","value":...}` لقيمة ثابتة، وهو النمط الوحيد للحقول المنطقية.
- `{"mode":"linear","from":... ,"to":...}` لتغير خطي خلال الفترة.
- `{"mode":"pulse","base":... ,"peak":... ,"peak_fraction":0.5}` لنبضة مثلثية تبلغ القمة عند نسبة زمنية بين 0 و1.

يُسمح لكل `event_type` بتغيير حقوله الخاصة فقط. يمكن أن تكون `changes: {}` في مرحلة مراقبة عادية (`normal_operation` أو `normal_environment`) لوصف التعافي بلا اختلاق مؤثر جديد. تُرفض مراحل التدخل الخالية من عينات معدلة، المراحل المتداخلة، والقيم غير الفيزيائية حتى لو كانت قمة النبضة تقع بين عينتين. يفصل البرنامج وصف المرحلة عن الاستجابة: التغير الفعلي لقنوات السرج ناتج من النموذج الفيزيائي وحالة الحساس، وليس موجة جاهزة من بطاقة حادثة. راجع [خطة اتساق البيانات](DATASET_COHERENCE_PLAN.md) قبل تكثير الحلقات أو التدريب.

## حدود التعميم قبل البيانات والتدريب

لا يولّد هذا الإصدار تسربًا، شقًا، خدشًا، فقد سماكة، أو مسافة كشف؛ تلك تحتاج دالة استجابة مكانية وبيانات تحقق مستقلة. كما أن تمثيل نقل الإجهاد عبر الطلاء واللاصق كـ `gain`/`lag` مبدئي إلى أن تُقاس هندسة التثبيت. جدول [متطلبات البيانات](DATA_READINESS.md) يبين ما يلزم لتحويل هذا المولد من فحص هندسي إلى مجموعة تدريب قابلة للدفاع عنها. ملف `manifest.json` يضبط `training_ready: false` عمدًا.
