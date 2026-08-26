import React from "react";
import { studentApi } from "@/lib/api";
import OutreachPage from "@/pages/OutreachPage";

// Delegated access: Lakshmi can grant a specific student the ability to
// send outreach emails on her behalf using her own saved templates (see
// /students/{sid}/outreach-access). Same UI and functionality as her own
// Outreach page, scoped to /student/outreach-templates and studentApi —
// except this student can never delete a template, and doesn't see the
// sent-log (that's Lakshmi's own oversight view).
export default function StudentOutreachPage() {
  return (
    <OutreachPage
      apiClient={studentApi}
      basePath="/student/outreach-templates"
      profileEndpoint="/student/me"
      canDelete={false}
      showLog={false}
    />
  );
}
