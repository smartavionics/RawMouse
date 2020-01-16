

NAME = RawMouse

FILES = $(addprefix $(NAME)/,$(shell git ls-files))

default: ../$(NAME).zip

../$(NAME).zip: *
	cd ..; zip -u $(NAME).zip $(FILES) -x $(NAME)/Makefile || true
