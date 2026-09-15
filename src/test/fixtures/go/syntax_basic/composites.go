package sample

type Embedded struct{}

type Pair[K comparable, V ~int | ~int64] struct {
	First, Second V
	*Embedded
	Tagged string `json:"tagged"`
}

type Service interface {
	Read(input string) (string, error)
	Embedded
}

func Convert[T ~int | ~int64](value T) T { return value }
