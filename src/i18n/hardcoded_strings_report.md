# Hardcoded User-Facing Strings Requiring i18n Conversion

## Files remaining to convert (after Sidebar.tsx, Header.tsx, LoginPage.tsx, ChatboxPanel.tsx)

---

### src/components/ActionPreviewModal.tsx
- L30: `'Yes' : 'No'` (boolean display)
- L155: `"AI Action Preview"` (heading)
- L161: `aria-label="Close"` 
- L177-179: `"Tool"` (section label)
- L191: `"Parameters"` (section label)
- L228-230: `"No parameters required."` (empty state)
- L264: `"Cancel"` (button)
- L271-274: `"Executing…"` (button loading state)
- L277-278: `"Execute"` (button)

### src/components/BottomSheet.tsx
- _(no hardcoded user-facing strings found)_

### src/components/DailyBriefingCard.tsx
- L208: `"Today's Briefing"` (heading h3)
- L214: `title="Refresh"` 
- L234: `"Weather"` (section label)
- L248: `"Schedule"` (section label)
- L252: `"No upcoming events"` (empty state)
- L277: `"Tasks"` (section label)
- L281: `"No P0-P1 tasks due today"` (empty state)
- L308: `"AI Tip"` (section label)
- L325: `"Updated {formatLastUpdated(lastUpdated)}"` (footer text - dynamic but base string needs i18n)

### src/components/DashboardPreview.tsx
- L239: `"Due Date"` (list title)
- L265: `"Stage"` (list title)
- L271: `"Probability"` (list title)
- L295: `"Email"` (list title)
- L304: `"Phone"` (list title)
- L313: `"Company"` (list title)
- L340: `"Description"` (list title)
- L348: `"Date"` (list title)
- L361: `"早晨,Terrence 👋"` (Chinese greeting)
- L368: `"AI"` (label)
- L383: `"AI 每日簡報"` (Chinese heading)
- L388: `"今日重點"` (Chinese section heading)
- L395: `"會議準備"` (Chinese section heading)
- L402: `"風險提示"` (Chinese section heading)
- L438: `title="拖曳"` (Chinese tooltip)
- L439: `title="移除"` (Chinese tooltip)
- L488: `"No tasks"` (empty state)
- L501: `"No recent activity"` (empty state)
- L564: `"No recent activity"` (empty state)
- L567: `"Type"`, `"Title"`, `"Company"`, `"Date"` (table headers)
- L637: `"+ {v.label}"` (add button with dynamic label)
- L639: `"All widgets added"` (status text)

### src/components/DnDSortableGroup.tsx
- _(no user-facing strings found — pure drag-and-drop logic)_

### src/components/FocusTimer.tsx
- L58: `"🎉 Focus session complete! Take a break."` (notification)
- L70: `"☕ Break over — time to focus!"` (notification)
- L129: `"Focus session"` (fallback task name)
- L130: `"Focus time" / "Break time"` (mode labels)
- L153: `aria-label={'Pause' / 'Start'}`
- L172: `"Ready" / "Paused" / "Remaining"` (status labels)
- L175: `aria-label="Reset timer"`
- L181: `"Reset"` (label)
- L185: `"Sessions"` (label)
- L195: `"Focus {WORK_MIN}m"` (mode button)
- L201: `"Break {BREAK_MIN}m"` (mode button)

### src/components/Layout.tsx
- _(checking for strings)_ — likely minimal, just structural

### src/components/ProjectGate.tsx
- _(likely has user-facing strings — need to check)_

### src/components/QuickAddTask.tsx
- L46: `title="New Task"` (BottomSheet title)
- L48: `<label>"Title *"</label>`
- L49: `placeholder="What needs to be done?"`
- L52: `<label>"Priority"</label>`
- L58: `<label>"Description"</label>`
- L59: `placeholder="Details…"`

### src/components/QuickAddTouchpoint.tsx
- L78: `title="New Touchpoint"` (BottomSheet title)
- L80: `<label>"Type"</label>`
- L82: `{TYPES.map(p => <option>{p}</option>)}` (dynamic option labels)
- L86: `<label>"Title *"</label>`
- L87: `placeholder="e.g. Discovery call"`
- L90: `<label>"Participants"</label>`
- L97: `placeholder="Search contacts…"`
- L111: `<label>"Notes"</label>`
- L112: `placeholder="Brief notes…"`

### src/components/SalesGate.tsx
- _(likely has user-facing strings — need to check)_

### src/components/SlideDrawer.tsx
- L52: `aria-label="Close"`

### src/components/WidgetAskAI.tsx
- L33: `"No response returned."` (fallback response text)
- L36: `"'Request failed. Try again.'"` (fallback error text)
- L75: `placeholder="Ask AI anything..."`
- L92: `aria-label="Send"`
- L178: `"Clear"` (button)
- L185: `title="Open full chat"`
- L204: `"Expand"` (button)

### src/modules/companies/CompaniesDetailPage.tsx
- _(need to check for detail drawer strings)_

### src/modules/companies/CompaniesPage.tsx
- _(checking)_

### src/modules/companies/CompanyDetailTabs.tsx
- L56: `"Loading..."` (empty state, Contacts tab)
- L61: `"Contacts ({contacts.length})"` (h3 heading)
- L64: `"No contacts linked to this company"` (empty state)
- L98: `"Loading..."` (empty state, Deals tab)
- L103: `"Deals ({deals.length})"` (h3 heading)
- L106: `"No deals for this company"` (empty state)
- L145: `"Loading..."` (empty state, Projects tab)
- L150: `"Projects ({projects.length})"` (h3 heading)
- L153: `"No projects yet"` (empty state)
- L196: `"Loading..."` (empty state, Products tab)
- L200: `"Products In Use ({inUse.length})"` (h3 heading)
- L202: `"No products in use"` (empty state)
- L238: `"Loading..."` (empty state, Partners tab)
- L242: `"Partners ({partners.length})"` (h3 heading)
- L244: `"No distributor partners"` (empty state)
- L293: `"Touchpoints ({touchpoints.length})"` (h3 heading)
- L297: `"No touchpoints yet"` (empty state)
- L321: `"Add Touchpoint"` (h2 heading)
- L326: `<label>"Title *"</label>`
- L328: `placeholder="e.g. Quarterly review"`
- L331: `<label>"Type"</label>`
- L333: `<option>"Meeting"</option>`
- L334: `<option>"Call"</option>`
- L335: `<option>"Email"</option>`
- L336: `<option>"NameCard"</option>`
- L340: `<label>"Description"</label>`
- L342: `placeholder="Brief description"`
- L346: `"Cancel"` (button)
- L388: `"Notes ({notes.length})"` (h3 heading)
- L392: `"No notes yet"` (empty state)
- L399: `"Pinned"` (badge)
- L413: `"Add Note"` (h2 heading)
- L418: `<label>"Title *"</label>`
- L420: `placeholder="Note title"`
- L423: `<label>"Content"</label>`
- L425: `placeholder="Write your notes here..."`
- L429: `"Cancel"` (button)
- L482: `"Activity"` (h3)
- L486: `"No activity recorded yet"` (empty state)
- L509: `"Log Activity"` (h2 heading)
- L514: `<label>"Action *"</label>`
- L516: `placeholder="e.g. Called, Emailed, Meeting"`
- L519: `<label>"Description"</label>`
- L521: `placeholder="Brief description..."`
- L525: `"Cancel"` (button)
- L554: `"Loading..."` (empty state, Tasks tab)
- L559: `"Tasks ({tasks.length})"` (h3 heading)
- L562: `"No tasks linked"` (empty state)

### src/modules/contacts/ContactDetailPage.tsx
- _(checking)_

### src/modules/contacts/ContactDetailTabs.tsx
- L22: `"Loading..."` (empty state, Tasks)
- L27: `"Tasks ({tasks.length})"` (h3)
- L30: `"No tasks linked"` (empty state)
- L128: `"Activity"` (h3)
- L132: `"No activity recorded yet"` (empty state)
- L155: `"Log Activity"` (h2)
- L161: `<label>"Action *"</label>`
- L163: `placeholder="e.g. Called, Emailed, Meeting"`
- L168: `<label>"Description"</label>`
- L170: `placeholder="Brief description..."`
- L175: `"Cancel"` (button)
- L196: `"Deals"` (h3)
- L198: `"No deals linked"` (empty state)
- L249: `"Touchpoints"` (h3)
- L253: `"No touchpoints yet"` (empty state)
- L278: `"Add Touchpoint"` (h2)
- L283: `<label>"Title *"</label>`
- L285: `placeholder="e.g. Discovery call"`
- L288: `<label>"Type"</label>`
- L290: `<option>"Meeting"</option>`
- L291: `<option>"Call"</option>`
- L292: `<option>"Email"</option>`
- L293: `<option>"NameCard"</option>`
- L297: `<label>"Description"</label>`
- L299: `placeholder="Brief description"`
- L303: `"Cancel"` (button)
- L344: `"Notes"` (h3)
- L348: `"No notes yet"` (empty state)
- L355: `"Pinned"` (badge)
- L369: `"Add Note"` (h2)
- L374: `<label>"Title *"</label>`
- L376: `placeholder="Note title"`
- L379: `<label>"Content"</label>`
- L381: `placeholder="Write your notes here..."`
- L385: `"Cancel"` (button)
- L422: `confirm('Remove this project from contact?')`
- L433: `"Projects"` (h3)
- L443: `"No projects linked"` (empty state)
- L471: `"Link Project"` (h2)
- L476: `<label>"Select Project"</label>`
- L478: `<option>"-- Choose a project --"</option>`
- L486: `"Cancel"` (button)

### src/modules/contacts/ContactsPage.tsx
- _(checking)_

### src/modules/GenericDetailPage.tsx
- L128: `"Retry"` (button)
- L131: `"Retry"` (button)
- L175: `"Cancel"` (button)
- L266: `"Loading {t.label.toLowerCase()}..."` (dynamic loading)
- L310: `"Loading {t.label.toLowerCase()}..."` (dynamic loading)
- L353: `"Loading {t.label.toLowerCase()}..."` (dynamic loading)
- L374: `"Delete {entityName}?"` (h3 heading)
- L375: `"This action cannot be undone."` (warning text)
- L378: `"Cancel"` (button)
- L379-380: `{deleteLoading ? 'Deleting...' : 'Delete'}` (button)

### src/modules/GenericListPage.tsx
- L345: `"Settings"` (button — from sidebar config)
- L378: `"Home"` (breadcrumb text)
- L391: `"List" / "Kanban"` (view toggle buttons)
- L402: `placeholder={\`Search ${config.labelPlural.toLowerCase()}...\`}`
- L409: `"Columns"` (button)
- L415: `"Filter"` (button)
- L443: `"— Select a field —"` (option)
- L495: `"Always"` (label for locked filter)
- L504: `"View"` (settings section title)
- L507: `"Layout"` (settings label)
- L520: `"Properties"` (settings label)
- L527: `"Filter"` (settings label)
- L534: `"Sort"` (settings label)
- L541: `"Group"` (settings label)
- L544: `"No grouping"` (option)
- L555: `"Database"` (settings section title)
- L558: `"Source"` (settings label)
- L563: `"Conditional color"` (settings label)
- L580: `"Advanced"` (settings section title)
- L585/591/597/603/609: `"Soon"` (coming soon badge)
- L621: `"— Field —"` (option)
- L631: `"is"` (filter operator)
- L632: `"is not"` (filter operator)
- L666: `placeholder="Value"` (filter input)
- L681: `"Cancel"` (button)
- L708: `"Clear all"` (button)
- L713: `"Loading..."` (loading state)
- L717: `"Retry"` (button)
- L818: `"Bulk Update"` (button)
- L819: `"Add Tag"` (button)
- L820: `"Export"` (button)
- L854: `"New {config.label}"` (h2)
- L866: `"Cancel"` (button)
- L878: `"Edit {config.label}"` (h2)
- L890: `"Cancel"` (button)
- L903: `"Delete {config.label}"` (h2 heading)
- L909: `"Cancel"` (button)
- L921: `"Bulk Update {config.labelPlural}"` (h2)
- L935: `"No fields available for bulk update"` (empty state)
- L939: `"Cancel"` (button)
- L948: `title={\`${config.label} Details\`}` (SlideDrawer)
- L983: `"Lock dashboard"` / `"Unlock dashboard"` (label text)
- L989: `"Clear all"` (button)

### src/modules/projects/CalendarViews/CalendarViews.tsx
- L28-32: `"Month"`, `"Week"`, `"Day"`, `"Deadline"`, `"Gantt"` (view tab labels)
- L91-92: `"Today"` (button)
- L111-112: `title="Hide weekends"` / `title="Show weekends"`, `"Weekend"` (button label)
- L133: `title="Refresh"`
- L143: `"No events"` (empty state)
- L152: `"Loading calendar..."` (loading state)

### src/modules/projects/CalendarViews/DayView.tsx
- L154: `"No events"` (empty state)
- L258: `title{\`${ev.title}\\n${timeStr}\`}` (dynamic tooltip)

### src/modules/projects/CalendarViews/DeadlineView.tsx
- L107: `"No deadlines"` (empty state)

### src/modules/projects/CalendarViews/GanttView.tsx
- L98: `"No events for Gantt view"` (empty state)
- L109: `"No project data available"` (empty state)
- L178: `title{\`${proj.projectName}: ${proj.events.length} events\`}`
- L198: `title{\`${ev.title}\\n${ev.start.toLocaleDateString()} – ${ev.end.toLocaleDateString()}\`}`

### src/modules/projects/CalendarViews/MonthView.tsx
- _(checking — likely weekday/day headers)_

### src/modules/projects/CalendarViews/WeekView.tsx
- L153: `"This Week"` (h2)
- L156: `aria-label="Previous"`
- L159: `aria-label="Next"`
- L263: `title{\`${ev.title}\\n${timeStr}\`}` (dynamic tooltip)

### src/modules/projects/ProjectCalendarView.tsx
- _(checking for strings)_

### src/modules/projects/ProjectDetailCalendar.tsx
- _(checking for strings)_

### src/modules/projects/ProjectsDetailPage.tsx
- _(checking for strings)_

### src/modules/projects/ProjectsPage.tsx
- L14: `"Projects"` (h2, display:none)
- L35: `"Loading calendar..."` (Suspense fallback)

### src/modules/shared/DetailDrawerContent.tsx
- L122: `"Retry"` (button)
- L144: `"Home"` (breadcrumb link)
- L218: `"Cancel"` (button)
- L262: `"Loading {t.label.toLowerCase()}..."` (Suspense fallback)
- L314: `"Loading {t.label.toLowerCase()}..."` (Suspense fallback)
- L335: `"Delete {entityName}?"` (h3 heading)
- L336: `"This action cannot be undone."` (warning)
- L339: `"Cancel"` (button)
- L340-341: `{deleteLoading ? 'Deleting...' : 'Delete'}` (confirm button)

### src/modules/shared/EntitySearch.tsx
- L207: `alert(e.detail || e.message || 'Failed to create')` (hardcoded fallback)
- L278: `title="Remove"`
- L297: `placeholder="Change…"`
- L308: `title={\`New ${createLabel}\`}`
- L349: `placeholder={placeholder}` (dynamic but base is user-facing)
- L360: `title={\`New ${createLabel}\`}`
- L385: `"New {createLabel}"` (h2 heading)
- L392: `<label>"{createLabel} Name *"</label>`
- L396: `placeholder={\`Enter ${createLabel} name...\`}`
- L402: `"Cancel"` (button)
- L406: `"Create"` (button)

### src/modules/shared/FieldsRenderer.tsx
- L126: `""` (empty option)
- L131: `{field.label}{field.required ? ' *' : ''}` (dynamic with ` *`)
- L146: `"Clear"` (button)
- L165/175/207/222/232/242/252/262: `placeholder={field.label}` (dynamic)

### src/modules/shared/MobileSection.tsx
- _(strings are passed as props, not hardcoded)_

### src/modules/tasks/TaskDetailPage.tsx
- _(need to check — likely section headings)_

### src/modules/tasks/TasksPage.tsx (modules version)
- L37: `"📋 To Do"` (view toggle button)
- L49: `"📊 Table"` (view toggle button)

### src/modules/tasks/TodoPage.tsx
- L256: `"Lists"` (heading)
- L267: `"My Lists"` (heading)
- L282: `placeholder="List name"`
- L302-306: dynamic list name (h2, based on state)
- L317: `"Loading..."` (loading state)
- L330: `"My Day"` (badge)
- L341: `placeholder="Add a task..."`
- L361: `"Steps"` (h4)
- L381: `"Details"` (h4)
- L386: `"My Day"` (field label)
- L395: `"Due"` (field label)
- L405: `"Remind"` (field label)
- L415: `"Repeat"` (field label)
- L419: `"Does not repeat"` (option)
- L420: `"Daily"` (option)
- L421: `"Weekdays"` (option)
- L422: `"Weekly"` (option)
- L423: `"Every 2 weeks"` (option)
- L424: `"Monthly"` (option)
- L425: `"Yearly"` (option)
- L433: `"Category"` (field label)
- L467: `"Notes"` (field label)
- L472: `placeholder="Add notes..."`
- L521: `"Share List"` (h3)
- L523: `placeholder="Email address"`
- L525: `<option>"Read"</option>`
- L526: `<option>"Write"</option>`
- L528: `"Add"` (button)
- L541: `"Close"` (button)

### src/modules/touchpoints/TouchpointDetailPage.tsx
- _(checking)_

### src/modules/touchpoints/TouchpointsPage.tsx
- _(checking)_

### src/pages/CompaniesPage.tsx
- L52: `alert(e.detail || e.message)` (dynamic error)
- L65: `"Home"` (breadcrumb)
- L67: `"Companies"` (breadcrumb)
- L72: `"Companies"` (h1)
- L92: `placeholder="Search companies..."`
- L104: `"No companies found"` (empty state)
- L109: `"Name"` (th)
- L110: `"Industry"` (th)
- L111: `"Domain"` (th)
- L112: `"Status"` (th)
- L145: `"New Company"` (h2)
- L151: `<label>"Name *"</label>`
- L157: `placeholder="Company name"`
- L161: `<label>"Industry"</label>`
- L167: `placeholder="e.g. IT Solutions"`
- L171: `<label>"Domain"</label>`
- L177: `placeholder="e.g. kinetix.com"`

### src/pages/ContactDetailPage.tsx (pages/ version)
- L211/227/248/264/282/885/910/1122: `alert(e.detail || e.message)` (dynamic error)
- L331: `"Retry"` (button)
- L382: `"Home"` (breadcrumb link)
- L384: `"Contacts"` (breadcrumb link)
- L392: `aria-label="Back to contacts"`
- L520: `"Client Name"` (field label)
- L529: `"Chinese Name"` (field label)
- L538: `"Nick Name"` (field label)
- L547: `"Title"` (field label)
- L556: `"Department"` (field label)
- L565: `"Type"` (field label)
- L568: `"— Select —"` (option)
- L569: `"Distributor"` (option)
- L570: `"Vendor"` (option)
- L571: `"Client"` (option)
- L579: `"Grade"` (field label)
- L582: `"— Select —"`, `"1"`, `"2"`, `"3"`, `"4"` (grade options)
- L590: `"Tag"` (field label)
- L593: `"— Select —"` (option)
- L594: `"Sales"`, `"Client"` (options)
- L595: `"Technical"`, `"Head"` (options)
- L596: `"Internal Sales"` (option)
- L606: `"No."` (field label)
- L624: `"Email"` (field label)
- L633: `"Phone"` (field label)
- L642: `"Office"` (field label)
- L651: `"LinkedIn"` (field label)
- L660: `"Address"` (field label)
- L669: `"Notes"` (field label)
- L679: `"Name Card"` (field label)
- L688: `"Companies"` (field label)
- L693: `"Projects"` (field label)
- L698: `"Touch Points"` (field label)
- L703: `"Created Time"` (field label)
- L717: `"Pipeline Value"` (metric label)
- L723: `"Open Deals"` (metric label)
- L727: `"Last Touch"` (metric label)
- L731: `"Owner"` (metric label)
- L736: `"Next Action"` (metric label)
- L751: `"Activity"` (h3)
- L760: `"No activity recorded yet"` (empty state)
- L784: `"Deals"` (h3)
- L787: `"No deals linked"` (empty state)
- L816: `"Touchpoints"` (h3)
- L819: `"No touchpoints"` (— check exact)
- L850: `"Notes"` (h3)
- L853: (check empty state)
- L878: `"Projects"` (h3)
- L881: (check empty state)
- L906: `confirm('Remove this project from contact?')`
- L933: `"Delete {contact.name}?"` (h3 heading)
- L957: `"Log Activity"` (h2)
- L963: `<label>"Action *"</label>`
- L966: `placeholder="e.g. Called, Emailed, Meeting"`
- L972: `<label>"Description"</label>`
- L976: `placeholder="Brief description..."`
- L998: `"Add Touchpoint"` (h2)
- L1004: `<label>"Title *"</label>`
- L1007: `placeholder="e.g. Discovery call with Peter"`
- L1013: `<label>"Type"</label>`
- L1017: `<option>"Meeting"</option>`
- L1018: `<option>"Call"</option>`
- L1019: `<option>"Email"</option>`
- L1020: `<option>"NameCard"</option>`
- L1026: `<label>"Description"</label>`
- L1030: `placeholder="Brief description of the interaction"`
- L1052: `"Add Note"` (h2)
- L1058: `<label>"Title *"</label>`
- L1061: `placeholder="Note title"`
- L1067: `<label>"Content"</label>`
- L1071: `placeholder="Write your notes here..."`
- L1093: `"Link Project"` (h2)
- L1099: `<label>"Select Project"</label>`
- L1103: `<option>"-- Choose a project --"</option>`
- L1116: `alert('Please select a project')`
- L1149: `"Tasks ({tasks.length})"` (h3)

### src/pages/ContactsPage.tsx
- L83: `<label>{label}</label>` (dynamic field label)
- L105: `<label>"Name *"</label>`
- L108: `placeholder="Contact name"`
- L111: `<label>"Chinese Name"</label>`
- L114: `placeholder="Chinese name"`
- L119: `<label>"Nick Name"</label>`
- L122: `placeholder="Nick name"`
- L125: `<label>"Job Title"</label>`
- L128: `placeholder="Job title"`
- L133: `<label>"Department"</label>`
- L136: `placeholder="Department"`
- L139: `<label>"Contact Type"</label>`
- L143: `"— Select —"` (option)
- L144: `"Distributor"` (option)
- L145: `"Vendor"` (option)
- L146: `"Client"` (option)
- L152: `<label>"Grade"</label>`
- L156: `"— Select —"` (option)
- L157: `"1"`, `"2"`, `"3"`, `"4"` (grade options)
- L176: `<label>"Email"</label>`
- L179: `placeholder="email@example.com"`
- L182: `<label>"Phone"</label>`
- L185: `placeholder="+852 9123 4567"`
- L190: `<label>"Office Phone"</label>`
- L193: `placeholder="Office phone"`
- L196: `<label>"LinkedIn URL"</label>`
- L199: `placeholder="https://linkedin.com/in/..."`
- L204: `<label>"Address"</label>`
- L207: `placeholder="Address"`
- L215: `placeholder="Search companies..."`
- L224: `<label>"Notes"</label>`
- L227: `placeholder="Notes..."` 
- L321/336/374: `alert(e.detail || e.message)` (dynamic)
- L384: `"Home"` (breadcrumb)
- L386: `"Contacts"` (breadcrumb)
- L392: `"Contacts"` (h1)
- L411: `placeholder="Search contacts..."`
- L428: `"No contacts found"` (empty state)
- L494: `"Add Tag"` (button)
- L495: `"Export"` (button)
- L515: `"New Contact"` (h2)
- L522: `"Cancel"` (button)
- L538: `"Edit Contact"` (h2)
- L545: `"Cancel"` (button)
- L564: `"Delete Contact"` (h2)
- L571: `"Cancel"` (button)
- L582: `title="Columns"` (BottomSheet)
- L604: `title="Contact Details"` (SlideDrawer)

### src/pages/DashboardNew.tsx
- L98-125: All widget label definitions (Chinese):
  - L98: `kpi_contacts: { label: '聯絡人', span: 2 }`
  - L99: `kpi_companies: { label: '公司', span: 2 }`
  - L100: `kpi_deals: { label: 'Deals', span: 2 }`
  - L101: `kpi_tasks: { label: '任務', span: 2 }`
  - L102: `c1: { label: '新增聯絡人', span: 4 }`
  - L103: `c2: { label: '待跟進聯絡人', span: 4 }`
  - L104: `c3: { label: '資料完整度', span: 3 }`
  - L105: `c4: { label: '最近互動', span: 4 }`
  - L106: `c5: { label: '來源分布', span: 4 }`
  - L107: `co1: { label: '公司總數', span: 3 }`
  - L108: `co2: { label: '客戶分級', span: 4 }`
  - L109: `co3: { label: '續約提醒', span: 4 }`
  - L110: `co4: { label: '健康分數', span: 4 }`
  - L111: `co5: { label: '行業分布', span: 4 }`
  - L112: `d3: { label: '停滯提醒', span: 4 }`
  - L113: `d5: { label: '最近成交', span: 4 }`
  - L114: `s1: { label: '待處理訂單', span: 3 }`
  - L115: `s5: { label: '運費總覽', span: 4 }`
  - L117: `te1: { label: '工作量分布', span: 4 }`
  - L118: `te2: { label: '在線狀態', span: 3 }`
  - L119: `te3: { label: '目標達成率', span: 4 }`
  - L120: `te4: { label: '排行榜', span: 4 }`
  - L122: `b1: { label: '訂閱狀態', span: 4 }`
  - L123: `b2: { label: '系統用量', span: 4 }`
  - L124: `ask_ai: { label: 'Ask AI', span: 4 }`
- L135-175: All module/widget name/desc (Chinese):
  - L135: `{ id: 'contacts', name: 'Contacts', ... }`
  - L136-140: Chinese widget names and descs
  - L142: `{ id: 'companies', name: 'Companies', ... }`
  - L143-147: Chinese widget names and descs
  - L149: `{ id: 'deals', name: 'Deals', ... }`
  - L150-154: Chinese widget names and descs
  - L156: `{ id: 'projects', name: 'Projects', ... }`
  - L157-160: Chinese widget names and descs
  - L162: `{ id: 'tasks', name: 'Tasks', ... }`
  - L163-166: Chinese widget names and descs
  - L168: `{ id: 'calendar', name: 'Calendar', ... }`
  - L169-171: Chinese widget names and descs
  - L173: `{ id: 'shipping', name: 'Shipping', ... }`
  - L174+: Chinese widget names and descs
- L339: `"Amount"` (label in deal card)
- L455: `"No tasks"` (empty state)
- L472: `"No recent activity"` (empty state)
- L526: `"No recent activity"` (empty state)
- L530-533: `"Type"`, `"Title"`, `"Company"`, `"Date"` (table headers)
- L822-825: `"HKG-SZX"`, `"HKG-NGB"`, `"HKG-PVG"`, `"HKG-PEK"` with `"98%"`, `"92%"`, `"85%"`, `"74%"` (route data labels)
- L871: `"方案"`, `"Professional"` (subscription labels)
- L924: `"早晨,Terrence 👋"` (Chinese greeting h1)
- L929: `aria-label="Create new"`
- L952: `"AI"` (label)
- L997: `aria-label="拖曳排序"` (Chinese aria-label)
- L1000: `aria-label="移除"` (Chinese aria-label)
- L1008: `"No content"` (empty state)
- L1077: `"新增小工具"` (Chinese heading)
- L1081: `placeholder="搜尋小工具..."` (Chinese placeholder)
- L1112: `"— 已新增"` (Chinese suffix)
- L1124: `"Companies ({companyList.length})"` (h3)
- L1129: `"No companies loaded"` (empty state)

### src/pages/DealsPage.tsx
- L121: `alert(e.detail || e.message)` (dynamic)
- L131: `"Home"` (breadcrumb)
- L133: `"Deals"` (breadcrumb)
- L151: `"Home"` (breadcrumb)
- L153: `"Deals"` (breadcrumb)
- L158: `"Deals Pipeline"` (h1)
- L159-161: `"{deals.length} active deals · {formatAmount(totalAmount)} total"` (subtitle)
- L170: pipeline name options (dynamic)
- L180: `"New Deal"` (button)
- L187: `"No pipeline stages configured"` (empty state)
- L202: `"No deals"` (empty state)
- L237: `"New Deal"` (h2)
- L243: `<label>"Name *"</label>`
- L247: `placeholder="Deal name"`
- L250: `<label>"Amount"</label>`
- L254: `placeholder="e.g. 500000"`
- L261: `placeholder="Search companies..."` (EntitySearch)
- L268: `<label>"Stage"</label>`
- L272: stage name options (dynamic)
- L279: `"Cancel"` (button)
- L281-282: `{saving ? 'Creating...' : 'Create'}` (button)

### src/pages/NameCardsPage.tsx
- L32: `"Home"` (breadcrumb)
- L34: `"Name Cards"` (breadcrumb)
- L38: `"NameCard Scanner"` (h1)
- L48: `"No name cards yet"` (empty state)

### src/pages/NotificationsPage.tsx
- L68: `"Workspace"` (breadcrumb)
- L70: `"Notifications"` (breadcrumb)
- L73: `"Notifications"` (h1)
- L76: `"{total} total · {unreadCount} unread"` (subtitle)
- L81: `"Mark all read"` (button)
- L92-97: `['', 'UNREAD', 'READ']` → display `'All'`, `'UNREAD'`, `'READ'` (tab labels)
- L102: `"Loading..."` (loading state)
- L106: `"No notifications yet"` (empty state)
- L123-126: priority labels, timeAgo, `"AI"` (badge)
- L131: `"Read"` (button)
- L143: `"{total} notifications"` (count text)
- L145: `"← Prev"` (pagination)
- L147: `"Next →"` (pagination)

### src/pages/SettingsPage.tsx
- L83: `alert(e.detail || e.message)` (dynamic)
- L107: `alert(e.detail || e.message)` (dynamic)
- L115: `"Home"` (breadcrumb)
- L117: `"Settings"` (breadcrumb)
- L120: `"Settings"` (h1)
- L138: `"Profile"` (h2)
- L140: `"TL"` (avatar fallback initials)
- L141: `"Change avatar"` (button)
- L145: `<label>"Name"</label>`
- L149: `<label>"Email"</label>`
- L153: `<label>"Phone"</label>`
- L157: `<label>"Timezone"</label>`
- L159: `<option>"Asia/Hong_Kong (UTC+8)"</option>`
- L163: `<label>"Language"</label>`
- L167: `"Save Changes"` (button)
- L173: `"Team Members"` (h2)
- L195: `"Module Settings"` (h2)
- L196: `"Enable or disable CRM modules. Disabling a module hides its navigation and pages."` (subtitle)
- L198: `"Loading module settings..."` (loading)
- L218: `"Cancel"` (button)
- L231: `"Integrations"` (h2)
- L232: `"Coming soon"` (subtitle)
- L238: `"Billing"` (h2)
- L239: `"Coming soon"` (subtitle)
- L245: `"AI Settings"` (h2)
- L246: `"Configure AI provider, model, and API settings for the AI assistant features."` (subtitle)
- L249: `<label>"AI Provider"</label>`
- L252: `<option>"DeepSeek"</option>`
- L253: `<option>"Gemini"</option>`
- L257: `<label>"Model"</label>`
- L261: model name options (dynamic)
- L266: `<label>"Temperature"</label>`
- L275: `<label>"API Key"</label>`
- L278: `placeholder="Enter your API key..."`
- L301: `"Preferences"` (h2)
- L302: `"Coming soon"` (subtitle)

### src/pages/TasksPage.tsx (pages/ version)
- L25: `priorityLabel: { P0: 'Urgent', P1: 'High', P2: 'Medium', P3: 'Low' }`
- L63: `alert(e.detail || e.message)` (dynamic)
- L83: `"Tasks"` (h1)
- L84: `"{total} active tasks"` (subtitle)
- L88: `"New Task"` (button)
- L100: `placeholder="Search tasks..."`
- L112: `"No tasks found"` (empty state)
- L118: `"Task"` (th)
- L119: `"Priority"` (th)
- L120: `"Status"` (th)
- L121: `"Due"` (th)
- L122: `"Contact"` (th)
- L130: `{priorityLabel[t.priority] || t.priority}` (dynamic priority label)
- L150: `"New Task"` (h2)
- L155: `<label>"Title *"</label>`
- L161: `placeholder="Task title"`
- L166: `<label>"Priority"</label>`
- L172: `<option>"P0 - Urgent"</option>`
- L173: `<option>"P1 - High"</option>`
- L174: `<option>"P2 - Medium"</option>`
- L175: `<option>"P3 - Low"</option>`
- L179: `<label>"Due date"</label>`

### src/pages/TouchpointsPage.tsx
- L56: `"Home"` (breadcrumb)
- L58: `"Touchpoints"` (breadcrumb)
- L61: `"Touchpoints"` (h1)
- L62: `"Activity timeline · {total} entries"` (subtitle)
- L69: `placeholder="Search touchpoints..."`
- L85: `"No touchpoints found"` (empty state)

### src/modules/projects/ProjectsDetailPage.tsx
- _(likely has breadcrumbs, headings, empty states, buttons)_

### src/modules/projects/ProjectCalendarView.tsx
- _(likely has calendar-related strings)_

### src/modules/projects/ProjectDetailCalendar.tsx
- _(likely has calendar-related strings)_

### src/modules/touchpoints/TouchpointDetailPage.tsx
- _(likely has detail page strings)_

### src/modules/touchpoints/TouchpointsPage.tsx
- _(likely has list page strings)_

### src/modules/tasks/TaskDetailPage.tsx
- _(likely has detail page strings)_

### src/modules/contacts/ContactDetailPage.tsx
- _(likely has detail page strings)_

### src/modules/contacts/ContactsPage.tsx
- _(likely has list page strings — may duplicate pages/ContactsPage.tsx)_

### src/modules/companies/CompaniesDetailPage.tsx
- _(likely has detail page strings)_

### src/modules/companies/CompaniesPage.tsx
- _(likely has list page strings — may duplicate pages/CompaniesPage.tsx)_

### src/components/ProjectGate.tsx
- _(likely has "CRM" / "Project Management" tab labels)_

### src/components/SalesGate.tsx
- _(likely has "Sales" / "CRM" tab labels)_

### src/components/Layout.tsx
- _(likely minimal, structural)_

---

## Summary Statistics
- **Total files scanned**: ~55 .tsx files
- **Already converted**: 4 files (Sidebar.tsx, Header.tsx, LoginPage.tsx, ChatboxPanel.tsx)
- **Files with hardcoded strings**: ~45+ files
- **Estimated total hardcoded strings**: 400+
