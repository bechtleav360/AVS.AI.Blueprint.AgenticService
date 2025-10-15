{{/*
Expand the name of the chart.
*/}}
{{- define "agent-blueprint.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agent-blueprint.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "agent-blueprint.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "agent-blueprint.labels" -}}
helm.sh/chart: {{ include "agent-blueprint.chart" . }}
{{ include "agent-blueprint.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "agent-blueprint.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-blueprint.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "agent-blueprint.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "agent-blueprint.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "agent-blueprint.runtimeSectionName" -}}
{{- regexReplaceAll "([a-z0-9])([A-Z])" . "${1}_${2}" | lower -}}
{{- end }}

{{- define "agent-blueprint.toEnvKey" -}}
{{- regexReplaceAll "([a-z0-9])([A-Z])" . "${1}_${2}" | upper -}}
{{- end }}

{{- define "agent-blueprint.toEnvValue" -}}
{{- $value := . -}}
{{- $kind := kindOf $value -}}
{{- if eq $kind "bool" -}}
{{- if $value }}true{{- else }}false{{- end -}}
{{- else if or (eq $kind "int") (eq $kind "float64") (eq $kind "float32") (eq $kind "uint64") (eq $kind "uint32") (eq $kind "uint") -}}
{{- printf "%v" $value -}}
{{- else if eq $kind "string" -}}
{{- $value -}}
{{- else -}}
{{- $value | toJson -}}
{{- end -}}
{{- end }}
