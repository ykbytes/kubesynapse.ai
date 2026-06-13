{{/*
Expand the name of the chart.
*/}}
{{- define "kubesynapse.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a chart label value.
*/}}
{{- define "kubesynapse.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "kubesynapse.fullname" -}}
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
Render an image reference from repository + optional digest/tag.
Digest wins over tag so callers can opt into immutable image references.
*/}}
{{- define "kubesynapse.imageRef" -}}
{{- $repository := .repository | default "" -}}
{{- $digest := .digest | default "" | trim -}}
{{- $tag := .tag | default "" | trim -}}
{{- if $digest -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else if $tag -}}
{{- printf "%s:%s" $repository $tag -}}
{{- else -}}
{{- $repository -}}
{{- end -}}
{{- end }}

{{/*
Render pod imagePullSecrets from values.global.imagePullSecrets.
*/}}
{{- define "kubesynapse.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels for all resources.
*/}}
{{- define "kubesynapse.labels" -}}
helm.sh/chart: {{ include "kubesynapse.chart" . }}
app.kubernetes.io/name: {{ include "kubesynapse.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Build a JSON object mapping MCP sidecar names to {image, port} for operator auto-injection.
*/}}
{{- define "kubesynapse.mcpSidecarCatalogJson" -}}
{{- $catalog := dict }}
{{- range $key, $val := .Values.mcpToolSidecars }}
{{- $image := $val.image }}
{{- $parts := splitList "/" $image }}
{{- $lastPart := index $parts (sub (len $parts) 1) }}
{{- if and $val.digest (not (contains "@" $image)) }}
{{- $image = printf "%s@%s" $val.image $val.digest }}
{{- else if and $val.tag (not (contains "@" $image)) (not (contains ":" $lastPart)) }}
{{- $image = printf "%s:%s" $val.image $val.tag }}
{{- end }}
{{- $_ := set $catalog $key (dict "image" $image "port" $val.port) }}
{{- end }}
{{- $catalog | toJson }}
{{- end }}

{{/*
Reuse an existing Secret value when the provided value is empty or still set to the chart's placeholder.
*/}}
{{- define "kubesynapse.secretValue" -}}
{{- $value := .value | default "" -}}
{{- $defaultValue := .default | default "" -}}
{{- $secretData := .secretData | default dict -}}
{{- $key := .key -}}
{{- $existingValue := (get $secretData $key | default "" | b64dec) -}}
{{- if and $existingValue (or (eq $value "") (and $defaultValue (eq $value $defaultValue))) -}}
{{- $existingValue -}}
{{- else -}}
{{- $value -}}
{{- end -}}
{{- end }}

{{/*
Return the secret name for Redis auth.
*/}}
{{- define "kubesynapse.redisAuthSecretName" -}}
{{- .Values.redis.auth.existingSecret | default (printf "%s-redis-auth" (include "kubesynapse.fullname" .)) -}}
{{- end }}

{{/*
Return the secret name for NATS auth.
*/}}
{{- define "kubesynapse.natsAuthSecretName" -}}
{{- .Values.nats.auth.existingSecret | default (printf "%s-nats-auth" (include "kubesynapse.fullname" .)) -}}
{{- end }}
