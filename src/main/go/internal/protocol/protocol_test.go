package protocol

import (
	"bytes"
	"errors"
	"strings"
	"testing"
)

func TestDecodeRequestAcceptsProtocolVersionOneFileRequest(t *testing.T) {
	request, err := DecodeRequest([]byte(
		`{"protocol_version":1,"type":"file","sequence":7,"path":"pkg/file.go"}`,
	))

	if err != nil {
		t.Fatalf("DecodeRequest() error = %v", err)
	}
	want := Request{ProtocolVersion: 1, Type: "file", Sequence: 7, Path: "pkg/file.go"}
	if request != want {
		t.Fatalf("DecodeRequest() = %#v, want %#v", request, want)
	}
}

func TestDecodeRequestRejectsInvalidContract(t *testing.T) {
	tests := map[string]string{
		"malformed":     `{`,
		"unknown field": `{"protocol_version":1,"type":"file","sequence":0,"path":"a.go","extra":true}`,
		"wrong version": `{"protocol_version":2,"type":"file","sequence":0,"path":"a.go"}`,
		"wrong type":    `{"protocol_version":1,"type":"close","sequence":0,"path":"a.go"}`,
		"negative seq":  `{"protocol_version":1,"type":"file","sequence":-1,"path":"a.go"}`,
		"empty path":    `{"protocol_version":1,"type":"file","sequence":0,"path":""}`,
		"trailing JSON": `{"protocol_version":1,"type":"file","sequence":0,"path":"a.go"}{}`,
		"empty input":   ``,
	}
	for name, input := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeRequest([]byte(input)); err == nil {
				t.Fatal("DecodeRequest() error = nil")
			}
		})
	}
}

func TestWriteResponseEncodesObservationAndDiagnosticPayloads(t *testing.T) {
	observation := Observation{
		SchemaVersion:    1,
		Kind:             "go.package",
		SourceID:         "file.go#package",
		Path:             "file.go",
		Confidence:       "extracted",
		Extractor:        "repo-go-ast",
		ExtractorVersion: "0.1.0",
		Metadata:         map[string]any{"static_only": true},
	}
	tests := []Response{
		{
			ProtocolVersion: ProtocolVersion,
			Type:            "observation",
			Sequence:        0,
			Path:            "file.go",
			Observation:     &observation,
		},
		{
			ProtocolVersion: ProtocolVersion,
			Type:            "diagnostic",
			Sequence:        0,
			Path:            "file.go",
			Severity:        "warning",
			Code:            "go-parse-error",
			Line:            2,
			Message:         "syntax error",
		},
	}
	for _, response := range tests {
		var output bytes.Buffer
		if err := WriteResponse(&output, response); err != nil {
			t.Fatalf("WriteResponse(%q) error = %v", response.Type, err)
		}
		if !strings.Contains(output.String(), `"type":"`+response.Type+`"`) {
			t.Fatalf("WriteResponse(%q) = %q", response.Type, output.String())
		}
	}
}

func TestWriteResponseRejectsInvalidPayloadsAndWriterFailures(t *testing.T) {
	invalid := []Response{
		{},
		{ProtocolVersion: 2, Type: "file_end", Sequence: 0, Path: "file.go"},
		{ProtocolVersion: 1, Type: "unknown", Sequence: 0, Path: "file.go"},
		{ProtocolVersion: 1, Type: "observation", Sequence: 0, Path: "file.go"},
		{ProtocolVersion: 1, Type: "diagnostic", Sequence: 0, Path: "file.go"},
		{ProtocolVersion: 1, Type: "file_end", Sequence: 0, Path: "file.go", ObservationCount: -1},
	}
	for _, response := range invalid {
		if err := WriteResponse(&bytes.Buffer{}, response); err == nil {
			t.Fatalf("WriteResponse(%#v) error = nil", response)
		}
	}
	valid := Response{
		ProtocolVersion: ProtocolVersion,
		Type:            "file_end",
		Sequence:        0,
		Path:            "file.go",
	}
	if err := WriteResponse(failingWriter{}, valid); err == nil {
		t.Fatal("WriteResponse() writer error = nil")
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) {
	return 0, errors.New("write failed")
}

func TestWriteResponseProducesDeterministicBoundedJSONLine(t *testing.T) {
	response := Response{
		ProtocolVersion:  ProtocolVersion,
		Type:             "file_end",
		Sequence:         3,
		Path:             "pkg/file.go",
		ObservationCount: 2,
		DiagnosticCount:  1,
		Truncated:        false,
	}
	var first bytes.Buffer
	var second bytes.Buffer

	if err := WriteResponse(&first, response); err != nil {
		t.Fatalf("WriteResponse() error = %v", err)
	}
	if err := WriteResponse(&second, response); err != nil {
		t.Fatalf("WriteResponse() second error = %v", err)
	}
	if first.String() != second.String() {
		t.Fatalf("WriteResponse() is not deterministic")
	}
	if !strings.HasSuffix(first.String(), "\n") {
		t.Fatalf("WriteResponse() missing newline: %q", first.String())
	}
}

func TestWriteResponseRejectsOversizedLine(t *testing.T) {
	response := Response{
		ProtocolVersion: ProtocolVersion,
		Type:            "diagnostic",
		Sequence:        0,
		Path:            "file.go",
		Severity:        "warning",
		Code:            "go-parse-error",
		Message:         strings.Repeat("x", MaxProtocolLineBytes),
	}

	if err := WriteResponse(&bytes.Buffer{}, response); err == nil {
		t.Fatal("WriteResponse() error = nil")
	}
}
