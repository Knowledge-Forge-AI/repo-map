module example.invalid/module-basic

go 1.25
toolchain go1.25.3

require (
	example.invalid/direct v1.2.3
	example.invalid/indirect v0.4.0 // indirect
	example.invalid/commented v0.5.0 // retained for compatibility
)

replace example.invalid/direct => ./local-direct
replace example.invalid/remote v1.0.0 => example.invalid/replacement v1.1.0
exclude example.invalid/bad v1.0.0
retract [v1.4.0, v1.4.2] // fixture regression
future value
